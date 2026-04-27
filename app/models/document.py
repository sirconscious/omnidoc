from app.core.database import execute_query

def insert_document(filename, file_type, file_size, minio_path):
    query = """
        INSERT INTO documents (filename, file_type, file_size, minio_path, status)
        VALUES (%s, %s, %s, %s, 'pending')
        RETURNING id
    """
    result = execute_query(
        query,
        (filename, file_type, file_size, minio_path),
        fetch=True
    )
    return result[0]["id"]

def update_status(doc_id, status, error_message=None):
    query = """
        UPDATE documents
        SET status = %s, error_message = %s
        WHERE id = %s
    """
    execute_query(query, (status, error_message, str(doc_id)))

def get_document(doc_id):
    query = "SELECT * FROM documents WHERE id = %s"
    result = execute_query(query, (str(doc_id),), fetch=True)
    return result[0] if result else None

def get_all_pending():
    query = "SELECT * FROM documents WHERE status = 'pending'"
    return execute_query(query, fetch=True)