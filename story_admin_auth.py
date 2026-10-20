# -*- coding: utf-8 -*-
"""Local editor gate. This is only a casual UI lock, NOT secure remote auth.

Credentials are readable in distributable EXEs. Do not use this to protect
private data or online server administration.
"""
import hmac

ADMIN_CODE = 'admin'
ADMIN_PASSWORD = 'pass123'


def validate_admin(code, password):
    if not isinstance(code, str) or not isinstance(password, str):
        return False
    return (hmac.compare_digest(code, ADMIN_CODE)
            and hmac.compare_digest(password, ADMIN_PASSWORD))
