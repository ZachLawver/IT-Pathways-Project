# 1. Import the SQL Server connection library.
import pyodbc

# 2. Configure the connection to our local TRACE database.
connection_string = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    r"SERVER=localhost\SQLEXPRESS;"
    "DATABASE=TRACE;"
    "Trusted_Connection=yes;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)

# 3. Establish a connection to SQL Server.
connection = pyodbc.connect(connection_string)
cursor = connection.cursor()

# 4. Verify the database connection.
cursor.execute("SELECT DB_NAME()")
database_name = cursor.fetchone()[0]

print(f"Connected successfully to: {database_name}")

# 5. Retrieve the tables in the TRACE database.
cursor.execute("""
    SELECT TABLE_NAME
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_TYPE = 'BASE TABLE'
    ORDER BY TABLE_NAME
""")

for row in cursor.fetchall():
    print(row[0])

# 6. Close the connection.
cursor.close()
connection.close()