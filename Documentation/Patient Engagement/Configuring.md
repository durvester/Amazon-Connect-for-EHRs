

# Configuring and testing patient engagement agents
<a name="configuring-testing-pe-agents"></a>

This section is intended for administrative and clinical staff who configure and test patient engagement agents.

After your administrator completes the steps in [Setting up Amazon Connect Health](setting-up.md), you can explore the AI agents, test them with your own EHR environment, and customize their behavior in the Amazon Connect Health application.

**Topics**
+ [Agent demo and testing](#cta-agent-demo)
+ [Agent customization](#cta-agent-customization)
+ [Sample contact flow for testing](#cta-sample-contact-flow)
+ [Communication channel support](#cta-channel-support)
+ [Next steps](#cta-next-steps)

## Agent demo and testing
<a name="cta-agent-demo"></a>

The Amazon Connect Health application home page provides two ways to experience the patient engagement AI agents:
+  **Hear Healthcare Agents in action** – Play a recorded conversation between a patient and the Amazon Connect Health agents. The demo shows how the agents verify a patient’s identity and schedule an appointment through natural conversation with contextual understanding. You can play the audio directly from the home page without prior configuration.
+  **Test your agent** – Experience a live conversation with the Amazon Connect Health agents integrated with your own EHR and Amazon Connect environment by calling your Amazon Connect provisioned number. This option becomes available after you complete EHR integration. Until then, you are prompted to configure your EHR setup.

## Agent customization
<a name="cta-agent-customization"></a>

After exploring the demo, you can tailor agent behavior to match your organization’s workflows.

1. On the home page, choose **Customize** on the Agent setup card.

1. Enable or disable scheduling capabilities – **Schedule**, **Reschedule**, **Cancel Appointments**, and **Verify Insurance**. Unchecked tasks are routed to a representative.

1. Configure three sequential identity verification steps by selecting required patient inputs, such as phone number or medical record number (MRN), date of birth, and zip code or last four Social Security number (SSN) digits.

1. Choose **Publish** to apply the updates.

For more information about customization options, see [Agent customization](agent-customization.md).

## Sample contact flow for testing
<a name="cta-sample-contact-flow"></a>

Amazon Connect Health provides a pre-built sample contact flow (`connect-health-{DOMAIN_ID}-inbound-flow`) for testing and operationalizing appointment management conversations powered by AI agents. The flow simulates a typical appointment scheduling conversation, including patient identity verification. You can use this flow to validate end-to-end agent behavior – including EHR data lookup, insurance verification, and escalation routing – before moving to production.

The sample flow is deployed automatically at domain creation, whether Amazon Connect Health creates a new Amazon Connect instance or you use an existing one.

For instructions on locating, using, and customizing the sample contact flow, see [Sample contact flow](contact-flow-setup.md).

## Communication channel support
<a name="cta-channel-support"></a>

Amazon Connect Health currently supports the voice channel through Amazon Connect. Web chat, SMS, and other digital channels are not supported in the current release.

## Next steps
<a name="cta-next-steps"></a>

After you configure and test your agents, explore the following topics:
+  [Patient engagement agents](patient-engagement-overview.md) – Learn about the patient verification and appointment management agents.
+  [Point of care agents](point-of-care-overview.md) – Learn about agents for clinical workflows.