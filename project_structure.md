prism/
├── .env
├── requirements.txt
│
├── app/
│   ├── __init__.py
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py          ← all env variables loaded here
│   │   └── database.py        ← postgres connection
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   └── minio_client.py    ← your minio code goes here
│   │
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── pdf_parser.py      ← PDF → text
│   │   ├── csv_parser.py      ← CSV → text
│   │   └── docx_parser.py     ← DOCX → text
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── document.py        ← document table queries (insert, update, get)
│   │
│   └── main.py                ← FastAPI app + routes
│
└── docker-compose.yml