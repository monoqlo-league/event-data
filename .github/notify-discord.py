"""チーム戦の対局記録の更新内容をまとめて Discord のウェブフックへ送る。

対象: 対局記録(YYYYMMXX-gamesN.csv)だけ。大会マスター・スケジュール・詳細成績のもと(-summary)の更新では通知しない。
対局数の数え方は、ランキングページと同じ(非表示の対局を除き、前のリーグのファイルにもある対局は数えない)。
DRY_RUN=1 のときは送らずに内容を表示するだけ。
"""
import csv
import io
import json
import os
import re
import subprocess
import sys
import urllib.request

MASTER = re.compile(r"^(\d{8})-master\.csv$")
SCHEDULE = re.compile(r"^(\d{8})-schedule\.csv$")
GAMES = re.compile(r"^(\d{8})-games(\d)\.csv$")
SUMMARY = re.compile(r"^(\d{8})-games(\d)-summary\.csv$")
ZERO = "0" * 40


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def read(rev, name):
    text = git("show", f"{rev}:{name}") if rev else None
    if text is None:
        return None
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


def event_info(rev, key):
    """大会名とリーグ名の一覧。大会マスターが無ければ番号で代わりにする。"""
    rows = read(rev, f"{key}-master.csv") or []
    title = next((r.get("大会名", "").strip() for r in rows if (r.get("大会名") or "").strip()), "")
    plan = next((r.get("リーグ構成", "").strip() for r in rows if (r.get("リーグ構成") or "").strip()), "")
    leagues = [x.split(":")[0].strip() for x in plan.split("/") if x.split(":")[0].strip()]
    return title or f"{key[:4]}年{int(key[4:6])}月のチーム戦", leagues


def league_name(leagues, k):
    return leagues[k - 1] if 0 < k <= len(leagues) else f"{k}次リーグ"


def game_ids(rows):
    """非表示を除いた対局の識別子(牌譜リンク、無ければ開始時間と4人)。"""
    out = []
    for r in rows or []:
        if (r.get("非表示状態") or "").strip().lower() == "yes":
            continue
        link = (r.get("牌譜リンク") or "").strip()
        if not link:
            who = [re.sub(r"^\[[^\]]*\]\[(\d+)\].*$", r"\1", (r.get(f"{i}位プレイヤー名") or "").strip()) for i in range(1, 5)]
            link = (r.get("開始時間") or "").strip() + "/" + ",".join(who)
        out.append(link)
    return out


def counts(rev, key):
    """リーグ番号 → 対局数。ランキングページと同じく、前のリーグのファイルにもある対局は数えない。"""
    seen, out = set(), {}
    for k in range(1, 10):
        rows = read(rev, f"{key}-games{k}.csv")
        if rows is None:
            continue
        n = 0
        for g in game_ids(rows):
            if g in seen:
                continue
            seen.add(g)
            n += 1
        out[k] = n
    return out


def planned(rev, key, league):
    """スケジュールにある、そのリーグの対局の数(卓の数の合計)。無ければ None。"""
    rows = read(rev, f"{key}-schedule.csv")
    if not rows:
        return None
    rows = [r for r in rows if (r.get("リーグ") or "").strip() == league]
    if not rows:
        return None
    seats = 0
    for r in rows:
        for c, v in r.items():
            if c and re.fullmatch(r"第\d+戦", c) and v and "抜け番" not in v and v.strip():
                seats += 1
    return seats // 4 or None


def test_message():
    """手動実行のときのテスト送信。いちばん新しい大会の、いちばん新しいリーグの対局数を添える。"""
    names = (git("ls-tree", "--name-only", "HEAD") or "").splitlines()
    keys = sorted({m.group(1) for n in names for m in [MASTER.match(n) or GAMES.match(n)] if m})
    lines = ["🔔 **通知のテスト**", "この通知が見えていれば、チーム戦ランキング更新の通知はこのチャンネルに届きます。"]
    if keys:
        key = keys[-1]
        title, leagues = event_info("HEAD", key)
        c = counts("HEAD", key)
        if c:
            k = max(c)
            lines.append(f"現在の最新:{title} {league_name(leagues, k)}(計{c[k]}局)")
        else:
            lines.append(f"現在の最新:{title}(対局記録はまだない)")
    return lines


def main():
    before = os.environ.get("BEFORE") or ""
    after = os.environ.get("AFTER") or "HEAD"
    if not before or before == ZERO or git("cat-file", "-e", before + "^{commit}") is None:
        before = (git("rev-parse", after + "^") or "").strip() or None
    diff = git("diff", "--name-only", before, after) if before else git("ls-tree", "--name-only", after)
    names = sorted(n for n in (diff or "").splitlines() if GAMES.match(n))

    lines = []
    if os.environ.get("EVENT") == "workflow_dispatch":
        names = []
        lines = test_message()
    cache = {}
    for n in names:
        m = MASTER.match(n) or SCHEDULE.match(n) or GAMES.match(n) or SUMMARY.match(n)
        key = m.group(1)
        title, leagues = event_info(after, key)
        if read(after, n) is None and MASTER.match(n):
            title, leagues = event_info(before, key)
        if MASTER.match(n):
            lines.append(f"・{title}の大会情報を{'削除' if read(after, n) is None else '追加' if read(before, n) is None else '更新'}")
        elif SCHEDULE.match(n):
            lines.append(f"・{title}の対局スケジュールを{'削除' if read(after, n) is None else '追加' if read(before, n) is None else '更新'}")
        elif SUMMARY.match(n):
            lg = league_name(leagues, int(m.group(2)))
            lines.append(f"・{title} {lg}の詳細成績を{'削除' if read(after, n) is None else '更新'}")
        else:
            k = int(m.group(2))
            lg = league_name(leagues, k)
            if key not in cache:
                cache[key] = (counts(before, key) if before else {}, counts(after, key))
            old, new = cache[key][0].get(k), cache[key][1].get(k)
            label = f"{title} {lg}"
            if new is None:
                lines.append(f"・{label}の対局記録を削除")
                continue
            if old is None:
                lines.append(f"・{label}の対局記録を追加(計{new}局)")
            elif new != old:
                lines.append(f"・{label}:{new - old:+d}局(計{new}局)")
            else:
                lines.append(f"・{label}の対局記録を更新(計{new}局)")
            # スケジュールの対局数に届いたら、そのリーグの終了を添える(ランキングページの「終了」と同じ判断)
            p = planned(after, key, lg) if leagues else None
            if p and new >= p and (old is None or old < p):
                lines.append(f"　🏁 {lg}が終了しました({p}局)")

    if not lines:
        print("通知する変更なし")
        return

    page = os.environ.get("PAGE_URL", "")
    head = [] if lines[0].startswith("🔔") else ["🀄 **チーム戦ランキングを更新しました**"]
    content = "\n".join(
        [*head, *lines, "", f"ランキング:{page}", "(ページへの反映に数分かかることがあります)"]
    )
    print(content)

    if os.environ.get("DRY_RUN"):
        return
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        print("DISCORD_WEBHOOK_URL が未設定のため、送信しない。")
        return
    body = json.dumps({"content": content, "allowed_mentions": {"parse": []}}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "event-data-notify (https://github.com/monoqlo-league/event-data, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print("送信しました:", r.status)
    except urllib.error.HTTPError as e:
        print("Discordへの送信に失敗:", e.code, e.read().decode("utf-8", "replace")[:300])
        sys.exit(1)


if __name__ == "__main__":
    main()
