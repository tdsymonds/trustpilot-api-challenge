import boto3, json, os, pip, shutil, time, uuid


################################################################################
# SETTINGS - UPDATE THESE ACCORDINGLY
################################################################################
# FUNCTION WIDE SETTINGS
AWS_REGION = 'eu-west-2'

# LAMBDA SETTINGS
LAMBDA_ROLE_NAME = 'LambdaRoleTPAPIChallenge'
LAMBDA_ROLE_DESCRIPTION = 'Role for TrustPilot API challenge lambda'
LAMBDA_FUNCTION_NAME = 'TrustPilotAPIChallengeLambda'
LAMBDA_FUNCTION_DESCRIPTION = "A lambda function for Trust Pilot's API challenge"
TMP_DIRECTORY_ROOT = '/tmp/trustpilotapi'

# API GATEWAY SETTINGS
API_GATEWAY_REST_API_NAME = 'TrustPilotChallengeAPI'
API_GATEWAY_REST_API_DESCRIPTION = 'The API for the Trust Pilot challenge'
API_GATEWAY_RESOURCE_PATH_PART = 'get-trustscore'
API_GATEWAY_STAGE_NAME = 'prod'
API_GATEWAY_REQUEST_VALIDATOR_NAME = 'Trust Pilot API request validator'
################################################################################


def main():
    # create the role for lambda
    lambda_role_arn = create_lambda_iam_role()
    
    # this is ugly but the next stage fails if I don't wait!
    time.sleep(10)

    # build the lambda function
    create_lambda_function(lambda_role_arn=lambda_role_arn)

    # create the api gateway setup
    api_url = create_api_gateway()

    # print out the url of the api
    print ('-------------------------------------------')
    print ('Function deployed successfully')
    print ('-------------------------------------------')
    print ('The endpoint for the URL is:')
    print (api_url)
    print ('-------------------------------------------')


def create_lambda_iam_role():
    """
    Creates an IAM role with the basic execution policy
    for lambda.
    """
    print ('Creating IAM Role for lambda function')

    client = boto3.client('iam')

    assume_role_policy = json.dumps({
        'Version': '2012-10-17',
        'Statement': [
            {
                'Action': 'sts:AssumeRole', 
                'Principal': {
                    'Service': 'lambda.amazonaws.com'
                }, 
                'Effect': 'Allow'
            }
        ]
    })

    response = client.create_role(
        Path='/',
        RoleName=LAMBDA_ROLE_NAME,
        AssumeRolePolicyDocument=assume_role_policy,
        Description=LAMBDA_ROLE_DESCRIPTION,
    )
    lambda_role_arn = response['Role']['Arn']

    # get the basic lambda execution policy and attach to the new role
    response = client.get_policy(
        PolicyArn='arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'
    )
    policy_arn = response['Policy']['Arn']
    response = client.attach_role_policy(
        RoleName=LAMBDA_ROLE_NAME,
        PolicyArn=policy_arn
    )

    print ('- Role created successfully.')
    return lambda_role_arn


def create_lambda_function(lambda_role_arn):
    """
    Moves the lambda function directory to temp location,
    installs the requirements into that temp location, zips
    these files and uploads to AWS lambda to create a function.
    """
    print ('Creating lambda function')
    # copy the lambda files to temp location
    current_directory = os.getcwd()
    lambda_directory = os.path.join(current_directory, 'lambda')
    tmp_directory_lambda = os.path.join(TMP_DIRECTORY_ROOT, 'lambda')

    shutil.rmtree(TMP_DIRECTORY_ROOT, ignore_errors=True)
    shutil.copytree(lambda_directory, tmp_directory_lambda)

    # install pip into temp directory
    pip.main(['install', '-r', 'lambda/requirements.txt', '-t' ,tmp_directory_lambda])

    # zip the contents to be sent to lambda
    zip_dir = os.path.join(TMP_DIRECTORY_ROOT, 'lambda_zip')
    zip_file = shutil.make_archive(zip_dir, 'zip', tmp_directory_lambda)

    # create lambada function
    client = boto3.client('lambda', region_name=AWS_REGION)
    response = client.create_function(
        FunctionName=LAMBDA_FUNCTION_NAME,
        Runtime='python3.6',
        Role=lambda_role_arn,
        Handler='lambda_function.lambda_handler',
        Code={
            'ZipFile': open(zip_file, 'rb').read()
        },
        Description=LAMBDA_FUNCTION_DESCRIPTION,
        Timeout=30,
        MemorySize=128,
    )

    print ('- Lambda funciton created successfully.')


def create_api_gateway():
    """
    Creates a REST API in API gateway, that has one method 
    and one resource specified in the settings, which calls
    the lambda function.

    The API has two query string parameters, domain and limit.

    The API is then deployed to be publically accessible, and
    end point is returned, with sample query string parameters.

    NOTE: There appears to be a problem creating GET requests
    with lambda through the SDK where it throws a forbidden error.
    This is discussed here:

    https://forums.aws.amazon.com/thread.jspa?messageID=745586&#745586

    It's also discussed on Github.

    So for now the POST http method is used.
    """
    print ('Creating API Gateway')

    API_GATEWAY_HTTP_METHOD = 'POST'

    client = boto3.client('apigateway', region_name=AWS_REGION)

    # first have to create the rest api
    response = client.create_rest_api(
        name=API_GATEWAY_REST_API_NAME,
        description=API_GATEWAY_REST_API_DESCRIPTION,
    )
    rest_api_id = response['id']

    # Get the api's root resource id
    response = client.get_resources(
        restApiId=rest_api_id,
    )
    root_id = response['items'][0]['id']

    # create the resource
    response = client.create_resource(
        restApiId=rest_api_id,
        parentId=root_id,
        pathPart=API_GATEWAY_RESOURCE_PATH_PART
    )
    resource_id = response['id']
    
    # add the GET method to the resource
    response = client.put_method(
        restApiId=rest_api_id,
        resourceId=resource_id,
        httpMethod=API_GATEWAY_HTTP_METHOD,
        authorizationType='NONE',
        apiKeyRequired=False,
        operationName='Get trust score',
    )

    # create integration
    lambda_client = boto3.client('lambda', region_name=AWS_REGION)
    lambda_version = lambda_client.meta.service_model.api_version
    account_id = boto3.client('sts').get_caller_identity().get('Account')

    uri_data = {
        'aws-region': AWS_REGION,
        'api-version': lambda_version,
        'aws-acct-id': account_id,
        'lambda-function-name': LAMBDA_FUNCTION_NAME,
    }

    # todo: surely there's a better way to do this?!
    uri = 'arn:aws:apigateway:{aws-region}:lambda:path/{api-version}/functions/arn:aws:lambda:{aws-region}:{aws-acct-id}:function:{lambda-function-name}/invocations'.format(**uri_data)

    client.put_integration(
        restApiId=rest_api_id,
        resourceId=resource_id,
        httpMethod=API_GATEWAY_HTTP_METHOD,
        type='AWS',
        integrationHttpMethod=API_GATEWAY_HTTP_METHOD,
        uri=uri,
    )

    client.put_integration_response(
        restApiId=rest_api_id,
        resourceId=resource_id,
        httpMethod=API_GATEWAY_HTTP_METHOD,
        statusCode='200',
        selectionPattern='-'
    )

    client.put_method_response(
        restApiId=rest_api_id,
        resourceId=resource_id,
        httpMethod=API_GATEWAY_HTTP_METHOD,
        statusCode='200',
    )


    # make updates to the various parts of the method
    body_mapping_template = """
        #set($limit = $input.params('limit'))
        {
            #if($limit && $limit.length() != 0)
                "limit": $input.params('limit'),
            #end
            "domain": "$input.params('domain')"
        }
    """
    client.update_integration(
        restApiId=rest_api_id,
        resourceId=resource_id,
        httpMethod=API_GATEWAY_HTTP_METHOD,
        patchOperations=[
            {
                'op': 'add',
                'path': '/requestTemplates/application~1json',
                'value': body_mapping_template,
            },
            {
                'op': 'replace',
                'path': '/passthroughBehavior',
                'value': 'WHEN_NO_TEMPLATES',
            }
        ]
    )

    # create request validator
    response = client.create_request_validator(
        restApiId=rest_api_id,
        name=API_GATEWAY_REQUEST_VALIDATOR_NAME,
        validateRequestBody=True,
        validateRequestParameters=True
    )
    request_validator_id = response['id']

    # update the method request with the validator and
    # add querystring
    client.update_method(
        restApiId=rest_api_id,
        resourceId=resource_id,
        httpMethod=API_GATEWAY_HTTP_METHOD,
        patchOperations=[
            {
                'op': 'replace',
                'path': '/requestValidatorId',
                'value': request_validator_id,
            },
            {
                'op': 'add',
                'path': '/requestParameters/method.request.querystring.domain',
                'value': 'true',
            },
            {
                'op': 'add',
                'path': '/requestParameters/method.request.querystring.limit',
                'value': 'false',
            }
        ]
    )

    # add lambda permission
    # NOTE: this is the part that fails when http method is get.
    uri_data['aws-api-id'] = rest_api_id
    uri_data['resource-path'] = API_GATEWAY_RESOURCE_PATH_PART
    uri_data['http-method'] = API_GATEWAY_HTTP_METHOD
    source_arn = 'arn:aws:execute-api:{aws-region}:{aws-acct-id}:{aws-api-id}/*/{http-method}/{resource-path}'.format(**uri_data)

    lambda_client.add_permission(
        FunctionName=LAMBDA_FUNCTION_NAME,
        StatementId=uuid.uuid4().hex,
        Action='lambda:InvokeFunction',
        Principal='apigateway.amazonaws.com',
        SourceArn=source_arn
    )

    # finally create the deployment
    response = client.create_deployment(
        restApiId=rest_api_id,
        stageName=API_GATEWAY_STAGE_NAME,
    )

    print ('- API Gateway successfully created.')

    api_data = {
        'aws-api-id': rest_api_id,
        'aws-region': AWS_REGION,
        'stage-name': API_GATEWAY_STAGE_NAME,
        'resource-path' : API_GATEWAY_RESOURCE_PATH_PART,
    }

    return 'https://{aws-api-id}.execute-api.{aws-region}.amazonaws.com/{stage-name}/{resource-path}?domain=google.co.uk&limit=10'.format(**api_data)


if __name__ == '__main__':
    main()
