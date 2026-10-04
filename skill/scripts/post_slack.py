#!/usr/bin/env python3
"""Post a /choices invite to Slack through an incoming webhook.

  post_slack.py setup <channel-name> <webhook-url>   save a channel's webhook (in ~/.config/choices/slack.json, mode 600)
  post_slack.py channels                              list saved channel names
  post_slack.py post <channel-name> --title T --url U [--text "…"] [--deadline D] [--from NAME] [--yes]

Without --yes, `post` prints the Slack payload and sends nothing: posting to a channel is outward-facing, so Claude
shows the user the exact message and only re-runs with --yes after they say send. Webhook URLs are secrets: never print,
log or commit them. This script only ever prints the channel *name*.
"""
import argparse
import json
import os
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path

CONFIG = Path(os.environ.get("CHOICES_CONFIG_DIR", Path.home() / ".config" / "choices")) / "slack.json"
WEBHOOK_PREFIX = "https://hooks.slack.com/"


def load():
    if not CONFIG.exists():
        return {}
    return json.loads(CONFIG.read_text())


def save(data):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(data, indent=2))
    os.chmod(CONFIG, stat.S_IRUSR | stat.S_IWUSR)


def payload(title, url, text, deadline, sender):
    intro = text or "I'd love your view: click your favourite in each section. Notes welcome, and you'll see everyone's votes live."
    context = []
    if deadline:
        context.append(f"Please choose by *{deadline}*")
    if sender:
        context.append(f"from {sender}")
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": title[:150], "emoji": False}},
        {"type": "section", "text": {"type": "mrkdwn", "text": intro[:2900]}},
        {"type": "actions", "elements": [{"type": "button", "style": "primary",
                                          "text": {"type": "plain_text", "text": "Open the choices"}, "url": url}]},
    ]
    if context:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(context)}]})
    fallback = f"{title}: {intro} {url}" + (f" (by {deadline})" if deadline else "")
    return {"text": fallback, "blocks": blocks}


def send(webhook, body):
    req = urllib.request.Request(webhook, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("channel")
    s.add_argument("webhook")
    sub.add_parser("channels")
    p = sub.add_parser("post")
    p.add_argument("channel")
    p.add_argument("--title", required=True)
    p.add_argument("--url", required=True)
    p.add_argument("--text")
    p.add_argument("--deadline")
    p.add_argument("--from", dest="sender")
    p.add_argument("--yes", action="store_true", help="actually send (only after the user approved the exact message)")
    a = ap.parse_args()

    if a.cmd == "setup":
        if not a.webhook.startswith(WEBHOOK_PREFIX):
            sys.exit(f"That doesn't look like a Slack incoming webhook (it should start with {WEBHOOK_PREFIX}).")
        data = load()
        data[a.channel.lstrip("#")] = a.webhook
        save(data)
        print(f"Saved webhook for #{a.channel.lstrip('#')} in {CONFIG} (private, mode 600).")
    elif a.cmd == "channels":
        names = sorted(load())
        print("\n".join(f"#{n}" for n in names) if names else "No Slack channels set up yet. Run: post_slack.py setup <channel> <webhook-url>")
    else:
        channel = a.channel.lstrip("#")
        hook = load().get(channel)
        body = payload(a.title, a.url, a.text, a.deadline, a.sender)
        if not a.yes:
            print(f"DRY RUN: nothing sent. This would post to #{channel}:\n")
            print(json.dumps(body, indent=2))
            if not hook:
                print(f"\nNote: #{channel} has no webhook saved yet. Run: post_slack.py setup {channel} <webhook-url>")
            return
        if not hook:
            sys.exit(f"#{channel} has no webhook saved. Run: post_slack.py setup {channel} <webhook-url>")
        status, text = send(hook, body)
        if status == 200:
            print(f"Posted to #{channel}.")
        else:
            sys.exit(f"Slack refused the post to #{channel}: HTTP {status} {text[:200]}")


if __name__ == "__main__":
    main()
