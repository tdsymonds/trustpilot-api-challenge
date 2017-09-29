from trustpilot.classes import TrustPilot


def lambda_handler(event, context):
    domain = event['domain']
    tp = TrustPilot(domain=domain)
    
    return {
        'domain': domain,
        'trust_score': tp.get_trustscore(),
    }
