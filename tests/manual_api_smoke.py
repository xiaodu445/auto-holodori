"""Tiny authenticated API test; sends no desktop data and never prints credentials."""
import json
from modular_agent.model_client import ModelConfig,create_model_client

def main():
    config=ModelConfig.from_json('config/model.json')
    try:
        output=create_model_client(config).complete(
            'Return JSON only: {"decision":"observe","reason":"test"}.',
            'This is a connectivity test; no screen or action is involved.')
        value=json.loads(output)
        assert value.get('decision')=='observe', 'Unexpected response schema'
        print(json.dumps({'api_test':'passed','model':config.model,'decision':value['decision']}))
    except Exception as error:
        print(json.dumps({'api_test':'failed','model':config.model,'error':str(error)}))
        raise SystemExit(1)

if __name__=='__main__': main()
