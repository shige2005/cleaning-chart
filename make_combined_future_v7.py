# -*- coding: utf-8 -*-
"""
清掃スケジュール（清掃スケジュール / 清掃スケジュール(HUB)）を読み、
未来21日（DAYS_PAST）のガント画像を作成 → Imgur → LINE送信
環境変数（GitHub Secrets）:
- GOOGLE_SERVICE_ACCOUNT_JSON
- SUNHOUSE_SHEET_ID
- HUB_SHEET_ID
- IMGUR_CLIENT_ID
- LINE_CHANNEL_ACCESS_TOKEN
- LINE_GROUP_ID_COMBINED
- DAYS_PAST (default 21)
"""

import os, json, requests
from datetime import date, timedelta
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from oauth2client.service_account import ServiceAccountCredentials
import gspread

# ---------- 環境変数 ----------
SA_ENV = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
SA_JSON = json.loads(SA_ENV) if SA_ENV.strip().startswith("{") else json.load(open(SA_ENV))
SUNHOUSE_SHEET_ID = os.environ.get("SUNHOUSE_SHEET_ID", "").strip()
HUB_SHEET_ID      = os.environ.get("HUB_SHEET_ID", "").strip()
IMGUR_CLIENT_ID   = os.environ.get("IMGUR_CLIENT_ID", "").strip()
LINE_TOKEN        = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
LINE_TO           = os.environ.get("LINE_GROUP_ID_COMBINED", "").strip()
DAYS              = int(os.environ.get("DAYS_PAST", "21"))

# ---------- 定数（並びと配色） ----------
ROOMS  = ["20","21","3","HUB405","HUB505"]
COLORS = {
    "20": "#FF7F27",   # サンセットオレンジ
    "21": "#C00000",   # 紅
    "3" : "#F6C6D8",   # 桜
    "HUB405": "#E1AD01",  # マスタード
    "HUB505": "#178F8F",  # ティール
}

# ---------- Google Sheets ----------
scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
gc = gspread.authorize(ServiceAccountCredentials.from_json_keyfile_dict(SA_JSON, scopes))

def read_tab(sheet_id: str, tab: str) -> pd.DataFrame:
    ws = gc.open_by_key(sheet_id).worksheet(tab)
    df = pd.DataFrame(ws.get_all_records())
    # 期待ヘッダー：部屋 / チェックイン / チェックアウト / 人数 / 備考
    cols = {c: c.strip() for c in df.columns}
    df = df.rename(columns=cols)
    return df

def normalize_records(df: pd.DataFrame, hub_prefix: str = ""):
    """部屋/チェックイン/チェックアウト/人数 を抽出し標準化"""
    out = []
    if df is None or df.empty:
        return out
    for _, r in df.iterrows():
        room = str(r.get("部屋", "")).strip()
        cin  = r.get("チェックイン")
        cout = r.get("チェックアウト")
        gs   = r.get("人数", "")
        if not room or not cin or not cout:
            continue
        # 日付に正規化
        cin  = pd.to_datetime(cin).date()
        cout = pd.to_datetime(cout).date()
        # HUBは部屋名をHUB接頭辞つきに
        if hub_prefix and not room.startswith(hub_prefix):
            room = f"{hub_prefix}{room}"
        gs_str = "" if (gs in ("", None)) else str(gs).strip()
        out.append(dict(room=room, checkin=cin, checkout=cout, guests=gs_str))
    return out

# ---------- 読み込み ----------
sun = read_tab(SUNHOUSE_SHEET_ID or HUB_SHEET_ID, "清掃スケジュール")
hub = read_tab(HUB_SHEET_ID or SUNHOUSE_SHEET_ID, "清掃スケジュール(HUB)")
records = normalize_records(sun, hub_prefix="") + normalize_records(hub, hub_prefix="HUB")

# ---------- 期間（未来→今日の降順） ----------
today = date.today()
start = today
end   = today + timedelta(days=DAYS-1)
ydays = [end - timedelta(days=i) for i in range(DAYS)]
ymap  = {d:i for i,d in enumerate(ydays)}         # 0 が最上段（未来）
xmap  = {r:i for i,r in enumerate(ROOMS)}         # 固定の列順

# ---------- 描画 ----------
fig, ax = plt.subplots(figsize=(10, 18))
for s in ["top","right","left","bottom"]:
    ax.spines[s].set_visible(False)
ax.tick_params(length=0)

# 祝日・週末ハイライト（最低限：日曜・土曜）
for y, d in enumerate(ydays):
    wd = d.weekday()  # Mon=0 ... Sun=6
    if wd == 6:
        ax.axhspan(y-0.5, y+0.5, facecolor="#FF0000", alpha=0.08)
    elif wd == 5:
        ax.axhspan(y-0.5, y+0.5, facecolor="#1E90FF", alpha=0.08)

# Y軸ラベル（月/日）
ax.set_yticks(list(range(len(ydays))))
ax.set_yticklabels([f"{d.month}/{d.day}" for d in ydays], fontsize=16)
ax.set_ylim(-0.5, len(ydays)-0.5)

# X軸：上段に部屋番号（HUBは数字のみ表示）
order = ['20','21','3','HUB405','HUB505']
xticks = [xmap[r] for r in order if r in xmap]
def room_label(r): return r.replace('HUB','') if r.startswith('HUB') else r
ax.set_xticks(xticks)
ax.set_xticklabels([room_label(r) for r in order if r in xmap], fontsize=28)

# 下段：SUNHOUSE / HUB ラベル（中央に1つ）
from statistics import mean
sun_keys = [k for k in ['20','21','3'] if k in xmap]
hub_keys = [k for k in ['HUB405','HUB505'] if k in xmap]
y_off = 1
if sun_keys:
    ax.text(mean([xmap[k] for k in sun_keys]), y_off, 'SUNHOUSE',
            transform=ax.get_xaxis_transform(), ha='center', va='top',
            fontsize=28, color='gray', fontweight='bold')
if hub_keys:
    ax.text(mean([xmap[k] for k in hub_keys]), y_off, 'HUB',
            transform=ax.get_xaxis_transform(), ha='center', va='top',
            fontsize=28, color='gray', fontweight='bold')
plt.subplots_adjust(bottom=0.12)

# バー描画
bars = 0
for b in records:
    room, cin, cout, gs = b["room"], b["checkin"], b["checkout"], b["guests"]
    if room not in xmap:
        continue
    seg_start = max(cin, start)
    seg_end   = min(cout, end)
    if seg_end < seg_start:
        continue
    idx_start = ymap.get(seg_start)
    idx_end   = ymap.get(seg_end)
    if idx_start is None or idx_end is None:
        continue

    y_top = min(idx_start + 0.0, idx_end + 0.4)
    y_bottom = max(idx_start + 0.0, idx_end + 0.4)
    height = max(0.05, y_bottom - y_top)
    x = xmap[room]

    ax.barh(y_top, width=0.8, left=x-0.4, height=height,
            color=COLORS.get(room, '#888888'), alpha=0.90, align='edge')

    # 中央文字：部屋番号の数字のみ
    num = ''.join(ch for ch in room if ch.isdigit()) or room
    ax.text(x, (y_top + y_bottom)/2, num, ha='center', va='center',
            fontsize=28, color='white')

    # CI（黒・左上内側）
    ax.text(x-0.37, idx_start, f"{cin:%-m/%-d}", fontsize=14,
            va='top', ha='left', color='#000000')

    # 人数（黒・右上内側）
    if gs:
        ax.text(x+0.37, idx_start, str(gs), fontsize=14,
                va='top', ha='right', color='#000000')

    # CO（赤・右下内側）
    ax.text(x+0.37, idx_end, f"{cout:%-m/%-d}", fontsize=26, fontweight='bold',
            va='bottom', ha='right', color='#C00000')
    bars += 1

print(f"[chart] bars: {bars}")

# ---------- 保存/送信 ----------
OUT = "out_combined_future.png"
plt.tight_layout()
plt.savefig(OUT, dpi=200, bbox_inches="tight")
print("[chart] saved:", OUT)

def upload_imgur(path: str) -> str | None:
    if not IMGUR_CLIENT_ID:
        print("[chart] skip Imgur: no client id")
        return None
    with open(path, "rb") as f:
        r = requests.post(
            "https://api.imgur.com/3/image",
            headers={"Authorization": f"Client-ID {IMGUR_CLIENT_ID}"},
            files={"image": f},
            timeout=30
        )
    print("[chart] Imgur:", r.status_code, str(r.text)[:200])
    if r.ok:
        j = r.json()
        if j.get("success"):
            return j["data"]["link"]
    return None

def push_line_image(url: str):
    if not (LINE_TOKEN and LINE_TO and url):
        print("[chart] skip LINE: missing token/to/url")
        return
    payload = {
        "to": LINE_TO,
        "messages": [{
            "type": "image",
            "originalContentUrl": url,
            "previewImageUrl": url
        }]
    }
    r = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Authorization": "Bearer " + LINE_TOKEN,
                 "Content-Type": "application/json"},
        json=payload,
        timeout=30
    )
    print("[chart] LINE:", r.status_code, str(r.text)[:200])

link = upload_imgur(OUT)
if link:
    push_line_image(link)
else:
    print("[chart] no image url -> LINE skipped")
#fix bracket typo
