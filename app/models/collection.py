from app.core.database import execute_query


def get_collection_by_name(name):
    query = "SELECT id FROM collections WHERE name = %s"
    result = execute_query(query, (name,), fetch=True)
    return result[0]["id"] if result else None