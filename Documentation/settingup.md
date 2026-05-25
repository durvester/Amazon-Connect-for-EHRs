

# Setting up Amazon Connect Health
<a name="setting-up"></a>

This section is intended for IT administrators who are responsible for setting up and configuring Amazon Connect Health.

Before you use Amazon Connect Health, complete the following tasks.

**Topics**
+ [Sign up for an AWS account](#setting-up-aws-sign-up)
+ [Create a user with administrative access](#setting-up-admin-user)
+ [Create an Amazon Connect Health domain](#setting-up-create-domain)
+ [Manage user access](#setting-up-manage-users)
+ [Enable single sign-on with Amazon Connect](#setting-up-sso)
+ [Access the Amazon Connect Health application](#setting-up-access-app)

## Sign up for an AWS account
<a name="setting-up-aws-sign-up"></a>

If you do not have an AWS account, complete the following steps to create one.

1. Open https://portal.aws.amazon.com/billing/signup.

1. Follow the online instructions.

   Part of the sign-up procedure involves receiving a phone call and entering a verification code on the phone keypad.

   When you sign up for an AWS account, an *AWS account root user* is created. The root user has access to all AWS services and resources in the account. As a security best practice, assign administrative access to a user, and use only the root user to perform [tasks that require root user access](https://docs.aws.amazon.com/accounts/latest/reference/root-user-tasks.html).

## Create a user with administrative access
<a name="setting-up-admin-user"></a>

After you sign up for an AWS account, secure your AWS account root user, enable AWS IAM Identity Center, and create an administrative user so that you don’t use the root user for everyday tasks.

### Secure your AWS account root user
<a name="setting-up-secure-root"></a>

1. Sign in to the [AWS Management Console](https://console.aws.amazon.com/) as the account owner by choosing **Root user** and entering your AWS account email address. On the next page, enter your password.

   For help signing in by using root user, see [Signing in as the root user](https://docs.aws.amazon.com/signin/latest/userguide/console-sign-in-tutorials.html#introduction-to-root-user-sign-in-tutorial) in the *AWS Sign-In User Guide*.

1. Turn on multi-factor authentication (MFA) for your root user.

   For instructions, see [Enable a virtual MFA device for your AWS account root user (console)](https://docs.aws.amazon.com/IAM/latest/UserGuide/enable-virt-mfa-for-root.html) in the *IAM User Guide*.

### Create a user with administrative access
<a name="setting-up-create-admin"></a>

1. Enable IAM Identity Center.

   For instructions, see [Enabling AWS IAM Identity Center](https://docs.aws.amazon.com/singlesignon/latest/userguide/get-set-up-for-idc.html) in the *AWS IAM Identity Center User Guide*.

1. In IAM Identity Center, grant administrative access to a user.

   For a tutorial about using the IAM Identity Center directory as your identity source, see [Configure user access with the default IAM Identity Center directory](https://docs.aws.amazon.com/singlesignon/latest/userguide/quick-start-default-idc.html) in the *AWS IAM Identity Center User Guide*.

### Sign in as the user with administrative access
<a name="setting-up-sign-in-admin"></a>

1. To sign in with your IAM Identity Center user, use the sign-in URL that was sent to your email address when you created the IAM Identity Center user.

   For help signing in using an IAM Identity Center user, see [Signing in to the AWS access portal](https://docs.aws.amazon.com/signin/latest/userguide/iam-id-center-sign-in-tutorial.html) in the *AWS Sign-In User Guide*.

## Create an Amazon Connect Health domain
<a name="setting-up-create-domain"></a>

A domain is a top-level container of resources and service configurations for Amazon Connect Health. You can have up to 10 domains in each account.

To create a domain, complete the following steps:

1. Sign in to the AWS Management Console and open the Amazon Connect Health console.

1. Choose **Create domain**.

1. Choose the scope of AI capabilities for the domain:
   +  **Agents for patient engagement** — Enables AI agents for automated administrative support for patients and EHR integration, with testing and agent customization provided in an application.
   +  **Agents for point of care** — Provides agents for use by healthcare professionals and office staff to support clinical workflows with a unified SDK.
   +  **For both** — Enables all patient engagement and point of care capabilities simultaneously.

1. Enter domain details:
   +  **Name** — Enter a domain name (for example, your EHR or health system name). Valid characters are a–z, A–Z, 0–9, underscore (\_), and hyphen (-), up to 100 characters.
   +  **Customize Encryption Settings** — Data is encrypted by default using an AWS managed key. Optionally, select **Customize encryption settings (advanced)** to use a customer managed key.
**Note**  
The remaining steps don’t apply to domains for point-of-care agents only. For point-of-care setup, see [Patient insights](patient-insights.md) and [Ambient documentation](ambient-documentation.md).

1. Add users through AWS IAM Identity Center to provide access to the Amazon Connect Health application.

1. (Optional) Configure an integration function. Set up an AWS Lambda function for the AI agent to perform insurance verification using your own insurance RTE vendor. See [sample-healthcare-realtime-eligibility](https://github.com/aws-samples/sample-healthcare-realtime-eligibility) on GitHub for a reference implementation. Choose **Create function** to build a new function, then enter the Lambda ARN in the provided field.

1. (Optional) Deploy a sample agent flow. Set up an Amazon Connect instance to deploy a sample contact flow and test the agent in an end-to-end patient conversation:
   +  **Skip for now** — Defer this setup to a later time.
   +  **Create and use a new Amazon Connect instance** (selected by default) — Recommended for most users. The access URL is auto-populated based on the domain name.
   +  **Use an existing Amazon Connect instance** — For organizations with an existing Amazon Connect instance.

**Important**  
Before you create a new Amazon Connect instance, check your service quota. By default, each account can have 2 Amazon Connect instances. To request a quota increase, see [Amazon Connect service quotas](https://docs.aws.amazon.com/connect/latest/adminguide/amazon-connect-service-limits.html) in the *Amazon Connect Administrator Guide*.

**Important**  
Inputs on the domain creation page cannot be changed after domain creation, except for fields marked as recommended.

## Manage user access
<a name="setting-up-manage-users"></a>

User access to the Amazon Connect Health application is managed through AWS IAM Identity Center. You can manage users in two ways:
+ Use the IAM Identity Center widget in the domain setup page to directly add users. This approach is ideal for quick testing.
+ Use the IAM Identity Center CLI or API to manage users, groups, and application assignments. This approach supports enterprise identity sources such as Active Directory and external identity providers. For more information, see [Users, groups, and provisioning in IAM Identity Center](https://docs.aws.amazon.com/singlesignon/latest/userguide/users-groups-provisioning.html).

**Important**  
Amazon Connect Health must be in the same AWS Region as your AWS IAM Identity Center instance. If they are in different Regions, you can [replicate your IAM Identity Center instance to an additional Region](https://docs.aws.amazon.com/singlesignon/latest/userguide/replicate-to-additional-region.html) or change your Amazon Connect Health Region.

## Enable single sign-on with Amazon Connect
<a name="setting-up-sso"></a>

To enable single sign-on (SSO) between Amazon Connect and Amazon Connect Health, assign the same IAM Identity Center user or user group to both applications. With SSO enabled, workforce users authenticate once and can access both Amazon Connect and Amazon Connect Health based on their enterprise identity.

Amazon Connect is available directly from the IAM Identity Center application catalog. See [Step-by-step instructions](https://static.global.sso.amazonaws.com/app-20950d6d247fd7bd/instructions/index.htm) to integrate Amazon Connect with IAM Identity Center using SAML 2.0.

## Access the Amazon Connect Health application
<a name="setting-up-access-app"></a>

After creating the domain, in the **Agents for patient engagement** section, choose **Open Application**. This launches the Amazon Connect Health application in your browser. If you don’t have a valid session, you are prompted to sign in with your configured identity provider.

You can bookmark and share the application URL for direct access by authorized users.