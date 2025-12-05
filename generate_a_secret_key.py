import secrets

# Generate a 50-character random secret key
SECRET_KEY = secrets.token_urlsafe(50)
print(SECRET_KEY)

