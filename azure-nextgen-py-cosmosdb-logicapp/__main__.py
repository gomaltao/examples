# Copyright 2016-2021, Pulumi Corporation.  All rights reserved.

import pulumi
import pulumi_azure_nextgen.authorization.latest as authorization
import pulumi_azure_nextgen.documentdb.latest as documentdb
import pulumi_azure_nextgen.logic.latest as logic
import pulumi_azure_nextgen.resources.latest as resources
import pulumi_azure_nextgen.storage.latest as storage
import pulumi_azure_nextgen.web.latest as web

# Create an Azure Resource Group
resource_group = resources.ResourceGroup("resourceGroup", resource_group_name="logicappdemo-rg")

# Create an Azure resource (Storage Account)
storage_account = storage.StorageAccount(
    "storageAccount",
    account_name="logicappdemosa21",
    resource_group_name=resource_group.name,
    sku=storage.SkuArgs(
        name=storage.SkuName.STANDARD_LRS,
    ),
    kind=storage.Kind.STORAGE_V2)

# Cosmos DB Account
cosmosdb_account = documentdb.DatabaseAccount(
    "cosmosdbAccount",
    account_name="logicappdemo-cdb",
    resource_group_name=resource_group.name,
    database_account_offer_type=documentdb.DatabaseAccountOfferType.STANDARD,
    locations=[documentdb.LocationArgs(
        location_name=resource_group.location,
        failover_priority=0,
    )],
    consistency_policy=documentdb.ConsistencyPolicyArgs(
        default_consistency_level=documentdb.DefaultConsistencyLevel.SESSION,
    ))

# Cosmos DB Database
db = documentdb.SqlResourceSqlDatabase(
    "db",
    database_name="sqldb",
    resource_group_name=resource_group.name,
    account_name=cosmosdb_account.name,
    resource=documentdb.SqlDatabaseResourceArgs(
        id="sqldb",
    ))

# Cosmos DB SQL Container
db_container = documentdb.SqlResourceSqlContainer(
    "dbContainer",
    container_name="container",
    resource_group_name=resource_group.name,
    account_name=cosmosdb_account.name,
    database_name=db.name,
    resource=documentdb.SqlContainerResourceArgs(
        id="container",
    ))

account_keys = pulumi.Output.all(cosmosdb_account.name, resource_group.name).apply(
    lambda arg: documentdb.list_database_account_keys(account_name=arg[0], resource_group_name=arg[1]))

client_config = pulumi.Output.from_input(authorization.get_client_config())

api_id = pulumi.Output.all(client_config.subscription_id, resource_group.location).apply(
    lambda arg: f"/subscriptions/{arg[0]}/providers/Microsoft.Web/locations/{arg[1]}/managedApis/documentdb")

# API Connection to be used in a Logic App
connection = web.Connection(
    "connection",
    connection_name="cosmosdbConnection",
    resource_group_name=resource_group.name,
    properties=web.ApiConnectionDefinitionPropertiesArgs(
        display_name="cosmosdb_connection",
        api=web.ApiReferenceArgs(
            id=api_id,
        ),
        parameter_values={
            "databaseAccount": cosmosdb_account.name,
            "access_key": account_keys.primary_master_key,
        },
    ))

# Logic App with an HTTP trigger and Cosmos DB action
workflow = logic.Workflow(
    "workflow",
    workflow_name="httpToCosmos",
    resource_group_name=resource_group.name,
    definition={
        "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
        "content_version": "1.0.0.0",
        "parameters": {
            "$connections": {
                "default_value": {},
                "type": "Object",
            },
        },
        "triggers": {
            "Receive_post": {
                "type": "Request",
                "kind": "Http",
                "inputs": {
                    "method": "POST",
                    "schema": {
                        "properties": {},
                        "type": "object",
                    },
                },
            },
        },
        "actions": {
            "write_body": {
                "type": "ApiConnection",
                "inputs": {
                    "body": {
                        "data": "@triggerBody()",
                        "id": "@utcNow()",
                    },
                    "host": {
                        "connection": {
                            "name": "@parameters('$connections')['documentdb']['connectionId']",
                        },
                    },
                    "method": "post",
                    "path": pulumi.Output.all(db.name, db_container.name).apply(
                        lambda arg: f"/dbs/{arg[0]}/colls/{arg[1]}/docs"),
                },
            },
        },
    },
    parameters={
        "$connections": logic.WorkflowParameterArgs(
            value={
                "documentdb": {
                    "connection_id": connection.id,
                    "connection_name": "logicapp-cosmosdb-connection",
                    "id": api_id,
                },
            },
        ),
    })

callback_urls = pulumi.Output.all(resource_group.name, workflow.name).apply(
    lambda arg: logic.list_workflow_trigger_callback_url(
        resource_group_name=arg[0],
        workflow_name=arg[1],
        trigger_name="Receive_post"))

# Export the HTTP endpoint
pulumi.export("endpoint", callback_urls.value)
