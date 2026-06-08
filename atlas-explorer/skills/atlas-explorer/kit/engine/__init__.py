"""The Atlas engine — repo-agnostic documentation navigator.

Everything repo-specific lives in atlas.config.yaml and curated/.
Engine modules must never reference a particular repository by name
(enforced by tests/test_reusability.py).
"""
