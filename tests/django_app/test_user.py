from django.contrib.auth import get_user_model


def get_or_create_test_user(
    username="testuser", email="test@example.com", password="testpassword"
):
    """
    Gets or creates a user for testing purposes.

    Returns:
        tuple: (user instance, created flag)
    """
    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=username, defaults={"email": email}
    )
    if created:
        user.set_password(password)
        user.save()
    print(f"test user updated/created")
    return user
