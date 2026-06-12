import sqlite3
conn = sqlite3.connect('/tmp/payroll.db')
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
print("Tables:")
for row in c.fetchall():
    print(" -", row[0])
print("\nTable schemas:")
c.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
for name, sql in c.fetchall():
    print(f"\n{name}:")
    print(sql)
conn.close()
