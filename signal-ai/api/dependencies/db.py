from infrastructure.database.mongodb import MongoDB

def get_db():
    return MongoDB.get_db()