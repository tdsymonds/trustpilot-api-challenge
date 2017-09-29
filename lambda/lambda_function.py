from trustpilot.classes import TrustPilot


def lambda_handler(event, context):
    domain = event['domain']
    limit = event.get('limit', 300)
    tp = TrustPilot(domain=domain)
    
    return {
        'domain': domain,
        'limit': limit,
        'trust_score': tp.get_trustscore(limit=limit),
    }
