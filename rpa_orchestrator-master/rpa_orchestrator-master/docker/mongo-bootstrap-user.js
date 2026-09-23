var username = _getEnv("MONGO_BOOTSTRAP_USERNAME");
var password = _getEnv("MONGO_BOOTSTRAP_PASSWORD");
var roles = [{ role: "root", db: "admin" }];

if (db.getUser(username) === null) {
    db.createUser({
        user: username,
        pwd: password,
        roles: roles
    });
} else {
    db.updateUser(username, {
        pwd: password,
        roles: roles
    });
}
