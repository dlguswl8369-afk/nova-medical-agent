"""NOVA preliminary Doctor + local BM25 retrieval entry point."""
from nova_sdk import run_agent
from nova_agent import prepare, consult

if __name__ == '__main__':
    run_agent(prepare, consult)
