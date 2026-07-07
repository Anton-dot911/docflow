"""Service-role Supabase client used by the repository layer.

The service-role key bypasses RLS, which is what the server needs to write
documents rows and Storage objects on the user's behalf before auth exists
(T2 placeholder user). Never expose this key or client to the frontend.
"""

from __future__ import annotations

import os
from functools import lru_cache

from supabase import Client, create_client


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Return a process-wide Supabase client authed with the service-role key.

    Raises KeyError at call time if the required env vars are unset, so unit
    tests (which inject fake clients into the repos) never touch this path.
    """
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)
