

# Appointment management agent
<a name="appointment-management-agent"></a>

The appointment management agent handles appointment scheduling, rescheduling, cancellations, and lookup through natural conversation integrated with real-time provider availability in EHR.

The appointment management agent handles full scheduling tasks from finding available slots across a provider’s locations to booking, rescheduling, and canceling appointments within a single intelligent conversation. With optional real-time insurance eligibility verification and copay transparency built into the booking flow, the agent reduces administrative friction for both patients and staff while ensuring care continuity. When specialized needs are detected, the agent escalates immediately to human staff with a complete summary including appointment details, patient preferences, and verification status, so no context is lost in the handoff.

**Topics**
+ [Capabilities](#am-capabilities)
+ [Configuration options](#am-configuration)

## Capabilities
<a name="am-capabilities"></a>

The Appointment management agent provides the following capabilities.
+  **New appointment scheduling with real-time provider availability lookup** – Finds available slots across a provider’s locations and books appointments within a single conversation.
+  **Appointment rescheduling and cancellation** – Retrieves the current appointment, presents available alternatives for rescheduling, or processes cancellations and provides confirmation to the patient.
+  **Appointment lookup and status confirmation** – Retrieves and confirms upcoming appointment details for the patient.
+  **Optional real-time insurance eligibility (RTE) verification** – Verifies insurance eligibility before confirming a booking. This feature requires a customer-managed AWS Lambda function.
+  **Copay transparency prior to appointment confirmation** – Provides copay information to the patient before the appointment is confirmed, so there are no surprises at the time of the visit.

## Configuration options
<a name="am-configuration"></a>

You can configure the following settings for the Appointment management agent.


| Setting | Description | 
| --- | --- | 
| Enabled capabilities | Choose which appointment actions are available to patients: schedule, reschedule, cancel, and lookup. Unchecked tasks are routed to a human representative. | 
| Insurance verification | Enable or disable real-time insurance eligibility verification. When enabled, the agent invokes a customer-managed Lambda function to check eligibility and retrieve copay information. For more information, see [Insurance verification integration](insurance-verification.md). | 
| AI Autonomy | Configure whether the appointment is fully self-serviced or preferences are collected and shared with staff for final action. | 