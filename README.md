# Sufala Sesame Management System

Django app for the sesame factory, local shops and Sufala franchises.

## Logins (after running `seed_demo`)
| Username | Role | Password |
|---|---|---|
| owner | Super Admin | sufala123 |
| factory | Factory Sub Admin | sufala123 |
| shopmain | Franchise Main Admin | sufala123 |
| shopstaff | Franchise Sub Admin | sufala123 |

Change these passwords before real use.

## Run on your computer
```
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```
Open http://127.0.0.1:8000. Without `DATABASE_URL` it uses a local SQLite file.

## Run the tests
```
python manage.py test core
```

## Deploy on Vercel
1. Create a free PostgreSQL database (Neon or Supabase, or add one from the Vercel Storage tab). Copy its connection string.
2. Push this folder to a GitHub repository.
3. In Vercel: Add New > Project > import the repository.
4. Before deploying, add Environment Variables:
   - `SECRET_KEY` = a long random string
   - `DEBUG` = `False`
   - `DATABASE_URL` = your PostgreSQL connection string (Vercel sets this itself if you added the database from Vercel)
5. Deploy. The build runs `collectstatic` and `migrate` automatically (see `pyproject.toml`).
6. Create the first owner account. Run once from your computer, pointing at the hosted database:
   ```
   DATABASE_URL="your-connection-string" python manage.py createsuperuser
   ```
   Then edit that user in `/admin/` and set Role = Super Admin. Or run `seed_demo` the same way for demo accounts.
7. Every `git push` redeploys automatically.

If the app shows a server error on Vercel, the usual cause is a missing `DATABASE_URL`.

## Structure
- `core/models.py` data model and stock ledger (`StockMovement`)
- `core/services.py` all business rules (inward, transfers, confirmation, sales, oil, waste)
- `core/views.py` role-based pages, `core/templates/core/` screens
- `core/tests.py` automated tests
