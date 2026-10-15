"""Use with official develop.py --agent PATH; never include in submission ZIP."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from nova_agent import prepare, consult as agent_consult


class LocalModelAdapter:
    def __init__(self, client):
        self.client = client

    def __getattr__(self, name):
        return getattr(self.client, name)

    def chat(self, messages, **kwargs):
        # The downloaded devkit still accepts only None or the old model alias.
        # Its configured Endpoint selects the actual local model independently.
        if kwargs.get('model') not in (None, 'openai/gpt-6-luna'):
            raise ValueError('UNEXPECTED_SUBMISSION_MODEL')
        kwargs.pop('model', None)
        return self.client.chat(messages, **kwargs)


def consult(client, state):
    return agent_consult(LocalModelAdapter(client), state)
