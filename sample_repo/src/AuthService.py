class AuthService:
    def __init__(self, user_repository, password_hasher):
        self.user_repository = user_repository
        self.password_hasher = password_hasher

    def authenticate(self, username, password):
        password_hash = self.user_repository.password_hash_for(username)
        return bool(password_hash and self.password_hasher.verify(password, password_hash))
