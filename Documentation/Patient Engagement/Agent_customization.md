

# Agent customization
<a name="agent-customization"></a>

After exploring the demo, you can tailor agent behavior to match your organization’s workflows. The customization page lets you configure scheduling capabilities, insurance verification, and identity verification steps.

The following table summarizes the customization areas available for each agent.


| Setting | Description | 
| --- | --- | 
| Scheduling capabilities | Select which appointment actions (schedule, reschedule, cancel, lookup) are available to patients. For more information, see [Appointment management agent](appointment-management-agent.md). | 
| Insurance verification | Enable or disable real-time insurance eligibility verification through customer-owned Lambda functions. For more information, see [Insurance verification integration](insurance-verification.md). | 
| AI autonomy | Configure whether the appointment is fully self-serviced or preferences are collected and shared with staff for final action. For more information, see [Appointment management agent](appointment-management-agent.md). | 
| Verification attributes | Select which factors (for example, medical record number (MRN), date of birth, zip code) are required for authentication. For more information, see [Patient verification agent](patient-verification-agent.md). | 

## To customize agent settings
<a name="ac-customize-procedure"></a>

1. Open the Amazon Connect Health console and choose **Customize** on the Agent setup card.

1. In the customization page, enable or disable scheduling capabilities:
   + Schedule appointments
   + Reschedule appointments
   + Cancel appointments
   + Verify insurance

     Unchecked tasks are routed to a representative.

1. Configure three sequential identity verification steps by selecting the required patient inputs:
   +  **Step 1** – Phone number or MRN
   +  **Step 2** – Date of birth
   +  **Step 3** – Zip code or last four digits of Social Security number (SSN)

1. Choose **Publish** to apply the updates.

### Expected results
<a name="expected-results"></a>

After you choose **Publish**, the updated configuration takes effect. The agent uses your selected scheduling capabilities and verification steps when handling patient interactions.