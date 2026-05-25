

# Insurance verification integration
<a name="insurance-verification"></a>

Real-time insurance eligibility (RTE) verification is an optional feature of the Appointment management agent. When enabled, the agent verifies a patient’s insurance eligibility and retrieves copay information prior to confirming an appointment. This feature is recommended for organizations that want to provide copay transparency before scheduling or rescheduling appointments.

**Topics**
+ [Overview](#iv-overview)
+ [How it works](#iv-how-it-works)
+ [Lambda input and output schema](#iv-lambda-schema)
+ [Lambda resource policy](#iv-resource-policy)
+ [Setup steps](#iv-setup-steps)

## Overview
<a name="iv-overview"></a>

Customers are responsible for creating and maintaining their Lambda function. AWS provides sample Lambda code that customers must update with their vendor-specific API integration details and authentication logic. Customers must deploy the Lambda to their AWS account, configure it with vendor credentials (using AWS Secrets Manager recommended), and add a resource policy allowing health-agent.amazonaws.com service principal to invoke the function.

### When to use insurance verification
<a name="iv-when-to-use"></a>

Use insurance verification integration when you want to:
+ Provide copay transparency to patients before confirming appointments
+ Integrate with your preferred RTE vendor (such as Experian Health or Waystar)

You don’t need RTE Lambda if:
+ Post-booking insurance verification through Epic’s private APIs is sufficient for your workflow
+ You prefer to handle insurance verification through existing staff processes

## How it works
<a name="iv-how-it-works"></a>

Insurance verification involves a setup phase and a runtime phase.

### Setup phase
<a name="iv-setup-phase"></a>

The customer deploys a Lambda function that connects to their preferred RTE vendor (for example, Experian Health or Waystar). The Lambda function is registered with Amazon Connect Health and granted invocation permissions.

### Runtime phase
<a name="iv-runtime-phase"></a>

When a patient schedules or reschedules an appointment, the Appointment management agent invokes the customer’s Lambda function with patient and appointment details. The Lambda function queries the RTE vendor and returns eligibility status and copay information to the agent, which presents the results to the patient before confirming the appointment.

## Lambda input and output schema
<a name="iv-lambda-schema"></a>

AWS provides sample Lambda code for patient insurance verification. You update the sample code with your vendor-specific integration details and deploy to your production account.

For the sample Lambda code, see [sample-healthcare-realtime-eligibility](https://github.com/aws-samples/sample-healthcare-realtime-eligibility) on GitHub.

### Input schema
<a name="iv-input-schema"></a>

The Appointment management agent provides the following information to your Lambda function.


| Field | Description | 
| --- | --- | 
| CoverageDetails.identifier | Payer code identifying the insurance company | 
| CoverageDetails.groupNumber | Insurance group number | 
| CoverageDetails.insuranceName | Free-text insurance name | 
| CoverageDetails.memberNumber | Subscriber’s member ID | 
| subscriber.identifier | System identifier for the subscriber (optional) | 
| subscriber.name | Subscriber name (optional) | 
| subscriber.dateOfBirth | Subscriber date of birth (optional) | 
| subscriber.relationshipToPatient | Relationship to the patient, for example "Self" (optional) | 
| patientIdentifier | Patient identifier | 
| requestPeriodStart | Service date start | 
| requestPeriodEnd | Service date end | 
| providerNPI | Provider’s 10-digit NPI | 
| providerLastName | Provider last name (optional) | 
| departmentNPI | Department NPI (optional) | 

### Output schema
<a name="iv-output-schema"></a>

Your Lambda function must return the following information to the Appointment management agent.


| Field | Type | Description | 
| --- | --- | --- | 
| eligibilityStatus | String | One of: `eligible`, `ineligible`, or `unknown`  | 
| copayAmount | Number (optional) | Estimated copay in USD | 
| coverageDetails | String (optional) | Free-text summary of coverage | 
| errorMessage | String (optional) | Error description if verification failed | 

## Lambda resource policy
<a name="iv-resource-policy"></a>

The customer must attach a resource-based policy to their Lambda function granting the Amazon Connect Health service principal invocation permissions. The policy must include:
+  **Effect**: Allow
+  **Principal Service**: `health-agent.amazonaws.com` 
+  **Action**: `lambda:InvokeFunction` 
+  **Resource**: Your Lambda function ARN
+  **Condition**: `ArnLike` with `AWS:SourceArn` matching `arn:aws:health-agent:<region>:<aws-account-id>:*` 

See [Granting Lambda function access to AWS services](https://docs.aws.amazon.com/lambda/latest/dg/permissions-function-services.html) for reference.

For the complete policy template, see the sample Lambda code at https://github.com/aws-samples/sample-healthcare-realtime-eligibility.

## Setup steps
<a name="iv-setup-steps"></a>

1. Download the sample Lambda code from https://github.com/aws-samples/sample-healthcare-realtime-eligibility.

1. Update the sample code with your RTE vendor’s API integration details and authentication logic.

1. Deploy the Lambda function to your AWS account.

1. Configure the Lambda function with vendor credentials using AWS Secrets Manager (recommended).

1. Attach the resource policy to grant Amazon Connect Health permission to invoke the function. For more information, see [Granting Lambda function access to AWS services](https://docs.aws.amazon.com/lambda/latest/dg/permissions-function-services.html) in the *AWS Lambda Developer Guide*.

1. In the Amazon Connect Health console, configure the Lambda function ARN in the domain settings under **Integration function**.

1. Test the integration in a non-production environment before enabling in production.