"""Seed the database with initial accounts, tags, and exclusions."""
import database as db

ACCOUNTS = {
    "binanceafrica": {
        "tags": [
            "winners", "create", "share+usdt", "share+usdc",
            "follow+repost", "follow+retweet", "giveaway",
            "follow+rt", "like+repost", "like+rt",
        ],
        "exclusions": [],
    },
    "binance": {
        "tags": [
            "win+usdc", "follow+repost", "giveaway",
            "follow+rt", "like+repost", "like+rt",
            "win+usdt", "reward+bnb", "reward+usdc",
        ],
        "exclusions": [],
    },
    "mexc_official": {
        "tags": ["winners"],
        "exclusions": ["trade", "referral"],
    },
    "htx_global": {
        "tags": ["follow+rt", "giveaway"],
        "exclusions": [],
    },
    "usaborat": {
        "tags": ["follow+rt", "giveaway", "create"],
        "exclusions": [],
    },
    "bitmartexchange": {
        "tags": ["follow+usdt", "create", "quote"],
        "exclusions": [],
    },
    "bybit_official": {
        "tags": ["winners+usdt"],
        "exclusions": ["trade"],
    },
}


def seed():
    db.init_db()
    for username, data in ACCOUNTS.items():
        added = db.add_account(username)
        status = "added" if added else "exists"
        print(f"@{username}: {status}")

        for tag in data["tags"]:
            db.add_account_keyword(username, tag)
        print(f"  tags: {data['tags']}")

        for ex in data["exclusions"]:
            db.add_account_exclusion(username, ex)
        if data["exclusions"]:
            print(f"  exclusions: {data['exclusions']}")

    print(f"\nTotal accounts: {len(db.list_accounts())}")
    for acc in db.list_accounts():
        tags = db.list_account_keywords(acc)
        excl = db.list_account_exclusions(acc)
        print(f"  @{acc}: {len(tags)} tags, {len(excl)} exclusions")


if __name__ == "__main__":
    seed()
