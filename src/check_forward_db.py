import sqlite3

DB = "data/forward/jarvis_forward.db"

conn = sqlite3.connect(DB)

print()
print("KANAL BAZLI INDIRILEN MEDYA")
print("-" * 60)

rows = conn.execute(
    """
    SELECT source_chat_title, COUNT(*)
    FROM telegram_messages
    WHERE media_path IS NOT NULL
    GROUP BY source_chat_title
    """
).fetchall()

for name, count in rows:
    print(f"{name}: {count}")

total = conn.execute(
    """
    SELECT COUNT(*)
    FROM telegram_messages
    WHERE media_type = 'photo'
    """
).fetchone()[0]

downloaded = conn.execute(
    """
    SELECT COUNT(*)
    FROM telegram_messages
    WHERE media_type = 'photo'
      AND media_path IS NOT NULL
    """
).fetchone()[0]

print()
print("FOTOGRAF DURUMU")
print("-" * 60)
print("Toplam fotoğraf:", total)
print("İndirilen:", downloaded)
print("Bekleyen:", total - downloaded)

conn.close()