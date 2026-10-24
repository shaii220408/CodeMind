class AuthService:
    def authenticate(self, username, password):
        return username == "admin" and password == "secret"
