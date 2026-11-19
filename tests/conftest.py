import pytest

from outreach.step3_qualify import Judgment
from outreach.step2_extract import CompanyProfile


class FakeLLM:
    """Returns canned objects per schema. `profile_fn(user_prompt)` builds the CompanyProfile."""

    def __init__(self, profile_fn=None, responses=None):
        self.profile_fn = profile_fn or (lambda user: CompanyProfile())
        self.responses = responses or {}
        self.calls = []

    def parse(self, *, system, user, schema, effort="medium"):
        self.calls.append((schema.__name__, user))
        if schema is CompanyProfile:
            return self.profile_fn(user)
        if schema.__name__ in self.responses:
            r = self.responses[schema.__name__]
            return r(user) if callable(r) else r
        if schema is Judgment:
            return Judgment(fit="strong", why_now_trigger="Selling to enterprises",
                            trigger_evidence="Enterprise plan with SSO", rationale="Fits the ICP.")
        raise AssertionError(f"unexpected schema {schema}")


@pytest.fixture
def fake_llm_cls():
    return FakeLLM
