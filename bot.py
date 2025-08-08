# ===== /check-lol: rank, top 5 thông thạo, 5 trận gần nhất (hardcode API key + DEBUG) =====
import json
import aiohttp
import discord
from discord.ext import commands
from discord_slash import SlashContext, SlashCommand
from discord_slash.utils.manage_commands import create_option

# Nếu bot & slash đã có sẵn ở file khác thì bỏ 3 dòng dưới.
bot = commands.Bot(command_prefix=">", intents=discord.Intents.all())
slash = SlashCommand(bot, sync_commands=True)

# ==== CONFIG: ĐIỀN API KEY TẠI ĐÂY ====
RIOT_API_KEY = "RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"  # <-- thay bằng key của bạn
RIOT_API_KEY = RIOT_API_KEY.strip()  # tránh thừa khoảng trắng/ký tự xuống dòng

DEFAULT_PLATFORM = "vn2"   # Summoner/League/Mastery v4
DEFAULT_REGION   = "asia"  # Match v5 (SEA/VN = asia)

# Bật/tắt log HTTP
DEBUG_HTTP = True

# Map platform (v4) -> region (v5)
PLATFORM_TO_REGION = {
    # Americas
    "na1": "americas", "la1": "americas", "la2": "americas", "br1": "americas",
    # Europe
    "euw1": "europe", "eun1": "europe", "tr1": "europe", "ru": "europe",
    # Asia / SEA
    "kr": "asia", "jp1": "asia",
    "sg2": "asia", "th2": "asia", "tw2": "asia", "ph2": "asia", "vn2": "asia",
}

# ===== Helpers =====
_CHAMP_CACHE = {}  # cache id -> name

def _dbg(msg: str):
    if DEBUG_HTTP:
        print("[LOL DEBUG]", msg)

def _mask(key: str) -> str:
    if not key:
        return "(empty)"
    return key[:6] + "…" + key[-4:]

def _headers():
    h = {"X-Riot-Token": RIOT_API_KEY}
    _dbg(f"Using header X-Riot-Token={_mask(RIOT_API_KEY)}")
    return h

def _platform_host(p: str) -> str:
    return f"https://{p}.api.riotgames.com"

def _region_host(r: str) -> str:
    return f"https://{r}.api.riotgames.com"

def _kda(k, d, a):
    if d == 0:
        return f"{k}/{d}/{a} (Perfect)"
    return f"{k}/{d}/{a} ({(k+a)/d:.2f})"

async def _champ_map(session: aiohttp.ClientSession):
    global _CHAMP_CACHE
    if _CHAMP_CACHE:
        return _CHAMP_CACHE
    async with session.get("https://ddragon.leagueoflegends.com/api/versions.json") as r:
        vers = await r.json()
    ver = vers[0]
    async with session.get(f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/champion.json") as r:
        data = await r.json()
    _CHAMP_CACHE = {int(v["key"]): v["name"] for v in data["data"].values()}
    return _CHAMP_CACHE

async def _get_json(session: aiohttp.ClientSession, url: str):
    _dbg(f"GET {url}")
    async with session.get(url, headers=_headers()) as resp:
        status = resp.status
        try:
            text = await resp.text()
        except Exception:
            text = ""
        _dbg(f"→ HTTP {status} | body[:200]={text[:200]!r}")

        if status == 403:
            raise PermissionError("API key không hợp lệ hoặc đã hết hạn (403).")
        if status == 401:
            raise PermissionError("401 Unknown apikey — kiểm tra lại X-Riot-Token.")
        if status == 429:
            raise RuntimeError("Quá giới hạn gọi API (429). Thử lại sau.")
        if status >= 400:
            raise RuntimeError(f"Lỗi API (HTTP {status}). {text[:180]}")
        return json.loads(text)

# ===== Slash command =====
@slash.slash(
    name="check-lol",
    description="Kiểm tra rank, top 5 thông thạo và 5 trận gần đây của tài khoản LMHT",
    options=[
        create_option(
            name="ten",
            description="Tên tài khoản (summoner name)",
            option_type=3,
            required=True,
        ),
        create_option(
            name="platform",
            description="Cụm v4 (mặc định vn2): vn2, sg2, th2, tw2, na1, euw1, kr...",
            option_type=3,
            required=False,
        ),
    ],
)
async def check_lol(ctx: SlashContext, ten: str, platform: str = None):
    await ctx.defer()
    platform = (platform or DEFAULT_PLATFORM).lower()
    region = PLATFORM_TO_REGION.get(platform, DEFAULT_REGION)
    _dbg(f"Platform host: {_platform_host(platform)} | Region host: {_region_host(region)}")

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            # 1) Summoner v4
            summ_url = f"{_platform_host(platform)}/lol/summoner/v4/summoners/by-name/{ten}"
            summ = await _get_json(session, summ_url)
            name  = summ["name"]
            level = summ.get("summonerLevel", "?")
            puuid = summ["puuid"]
            summ_id = summ["id"]

            # 2) League v4 (rank)
            league_url = f"{_platform_host(platform)}/lol/league/v4/entries/by-summoner/{summ_id}"
            leagues = await _get_json(session, league_url)
            rank_text = "Unranked"
            prefer = ["RANKED_SOLO_5x5", "RANKED_FLEX_SR"]
            leagues.sort(key=lambda x: prefer.index(x["queueType"]) if x["queueType"] in prefer else 99)
            if leagues:
                q = leagues[0]
                tier = q.get("tier", "")
                rnk  = q.get("rank", "")
                lp   = q.get("leaguePoints", 0)
                w    = q.get("wins", 0)
                l    = q.get("losses", 0)
                qname = "Solo/Duo" if q["queueType"] == "RANKED_SOLO_5x5" else "Flex"
                rank_text = f"{qname}: {tier} {rnk} - {lp} LP ({w}W/{l}L)"

            # 3) Mastery v4 (top 5)
            mastery_url = f"{_platform_host(platform)}/lol/champion-mastery/v4/champion-masteries/by-summoner/{summ_id}"
            mastery = await _get_json(session, mastery_url)
            top5 = mastery[:5] if isinstance(mastery, list) else []
            cmap = await _champ_map(session)
            mastery_lines = [
                f"- {cmap.get(m['championId'], m['championId'])}: {m['championPoints']:,} điểm • Lv{m['championLevel']}"
                for m in top5
            ] or ["(Chưa có dữ liệu thông thạo)"]

            # 4) Match v5 (5 trận gần nhất)
            ids_url = f"{_region_host(region)}/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count=5"
            match_ids = await _get_json(session, ids_url)
            recent_lines = []
            for mid in match_ids:
                murl = f"{_region_host(region)}/lol/match/v5/matches/{mid}"
                mdata = await _get_json(session, murl)
                me = next((p for p in mdata["info"]["participants"] if p["puuid"] == puuid), None)
                if not me:
                    continue
                win = "Thắng ✅" if me.get("win") else "Thua ❌"
                recent_lines.append(
                    f"- {win} • {me.get('championName','?')} • KDA: {_kda(me.get('kills',0), me.get('deaths',0), me.get('assists',0))} • "
                    f"Queue: {mdata['info'].get('queueId','')} • `{mid}`"
                )
            if not recent_lines:
                recent_lines = ["(Không lấy được lịch sử gần đây)"]

        # Trả về embed
        embed = discord.Embed(
            title=f"LMHT — {name}",
            description=f"Cấp độ: **{level}**\nMáy chủ: **{platform.upper()}**  •  Region: **{region.upper()}**",
            color=0x00ADEF
        )
        embed.add_field(name="Rank", value=rank_text, inline=False)
        embed.add_field(name="Top 5 tướng thông thạo", value="\n".join(mastery_lines), inline=False)
        embed.add_field(name="5 trận gần nhất", value="\n".join(recent_lines), inline=False)
        await ctx.send(embed=embed)

    except PermissionError as e:
        await ctx.send(f"❌ {e}")
    except aiohttp.ClientConnectorError as e:
        await ctx.send(f"❌ Không thể kết nối API (DNS/Network). Kiểm tra mạng/host.\n{e}")
    except Exception as e:
        await ctx.send(f"❌ Lỗi: {e}")

# Nếu file này là file bot chính, bỏ comment để chạy:
# bot.run("YOUR_DISCORD_TOKEN")
