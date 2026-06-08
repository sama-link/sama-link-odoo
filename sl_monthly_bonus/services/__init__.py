# The Edara proxy HTTP client lives here. It performs NO ORM writes; callers
# (the sync wizard / sync model) are responsible for staging persistence.
from . import edara_client
