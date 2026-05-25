"""Tests for fhir_query projections — voice-safe field extraction.

Each projection strips clinical values (lab results, dosages, diagnoses,
clinical notes) and returns only metadata safe to read aloud over the phone.
"""

from __future__ import annotations

import pytest

from fhir_query.projections import (
    project_allergy_intolerance,
    project_care_plan,
    project_care_team,
    project_condition,
    project_diagnostic_report,
    project_document_reference,
    project_encounter,
    project_goal,
    project_immunization,
    project_medication_request,
    project_observation,
    project_procedure,
    project_resource,
)


# ---------------------------------------------------------------------------
# DiagnosticReport
# ---------------------------------------------------------------------------

class TestDiagnosticReportProjection:
    FULL_REPORT = {
        "resourceType": "DiagnosticReport",
        "id": "dr-001",
        "status": "final",
        "category": [
            {
                "coding": [
                    {"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "LAB", "display": "Laboratory"}
                ]
            }
        ],
        "code": {
            "coding": [{"system": "http://loinc.org", "code": "58410-2", "display": "Complete blood count"}],
            "text": "CBC",
        },
        "effectiveDateTime": "2026-05-20T10:30:00Z",
        "issued": "2026-05-20T14:00:00Z",
        "performer": [{"display": "Quest Diagnostics"}],
        "result": [
            {"reference": "Observation/obs-wbc", "display": "WBC"},
            {"reference": "Observation/obs-rbc", "display": "RBC"},
        ],
        "conclusion": "All values within normal range.",
    }

    def test_extracts_safe_fields(self):
        result = project_diagnostic_report(self.FULL_REPORT)
        assert result["status"] == "final"
        assert result["category"] == "Laboratory"
        assert result["code_display"] == "Complete blood count"
        assert result["effective_date"] == "2026-05-20"
        assert result["issued_date"] == "2026-05-20"
        assert result["performer_name"] == "Quest Diagnostics"

    def test_strips_result_values(self):
        result = project_diagnostic_report(self.FULL_REPORT)
        assert "result" not in result
        assert "conclusion" not in result

    def test_handles_missing_fields(self):
        minimal = {"resourceType": "DiagnosticReport", "id": "dr-002", "status": "preliminary"}
        result = project_diagnostic_report(minimal)
        assert result["status"] == "preliminary"
        assert result["category"] == ""
        assert result["code_display"] == ""
        assert result["effective_date"] == ""
        assert result["performer_name"] == ""


# ---------------------------------------------------------------------------
# MedicationRequest
# ---------------------------------------------------------------------------

class TestMedicationRequestProjection:
    FULL_MED = {
        "resourceType": "MedicationRequest",
        "id": "med-001",
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "197361", "display": "Lisinopril 10 MG Oral Tablet"}],
            "text": "Lisinopril 10mg",
        },
        "authoredOn": "2026-04-15",
        "requester": {"display": "Dr. Sarah Chen"},
        "dosageInstruction": [
            {"text": "Take 1 tablet by mouth daily", "timing": {"repeat": {"frequency": 1, "period": 1, "periodUnit": "d"}}}
        ],
        "dispenseRequest": {"numberOfRepeatsAllowed": 3, "quantity": {"value": 30, "unit": "tablets"}},
    }

    def test_extracts_safe_fields(self):
        result = project_medication_request(self.FULL_MED)
        assert result["medication_name"] == "Lisinopril 10mg"
        assert result["status"] == "active"
        assert result["authored_date"] == "2026-04-15"
        assert result["requester"] == "Dr. Sarah Chen"

    def test_strips_dosage(self):
        result = project_medication_request(self.FULL_MED)
        assert "dosageInstruction" not in result
        assert "dosage" not in result
        assert "dispenseRequest" not in result

    def test_handles_missing_fields(self):
        minimal = {"resourceType": "MedicationRequest", "id": "med-002", "status": "stopped"}
        result = project_medication_request(minimal)
        assert result["status"] == "stopped"
        assert result["medication_name"] == ""
        assert result["authored_date"] == ""
        assert result["requester"] == ""

    def test_medication_reference_fallback(self):
        med_ref = {
            "resourceType": "MedicationRequest",
            "id": "med-003",
            "status": "active",
            "medicationReference": {"display": "Metformin 500mg"},
        }
        result = project_medication_request(med_ref)
        assert result["medication_name"] == "Metformin 500mg"


# ---------------------------------------------------------------------------
# Encounter
# ---------------------------------------------------------------------------

class TestEncounterProjection:
    FULL_ENCOUNTER = {
        "resourceType": "Encounter",
        "id": "enc-001",
        "status": "finished",
        "class": {"code": "AMB", "display": "ambulatory"},
        "type": [
            {
                "coding": [{"system": "http://snomed.info/sct", "code": "185349003", "display": "Encounter for check up"}],
                "text": "Office Visit",
            }
        ],
        "period": {"start": "2026-05-18T09:00:00Z", "end": "2026-05-18T09:30:00Z"},
        "participant": [
            {"individual": {"display": "Dr. James Wilson"}, "type": [{"text": "primary performer"}]}
        ],
        "diagnosis": [
            {"condition": {"display": "Essential hypertension"}, "rank": 1}
        ],
        "reasonCode": [{"text": "Annual physical"}],
    }

    def test_extracts_safe_fields(self):
        result = project_encounter(self.FULL_ENCOUNTER)
        assert result["status"] == "finished"
        assert result["type"] == "Encounter for check up"
        assert result["date"] == "2026-05-18"
        assert result["practitioner_name"] == "Dr. James Wilson"
        assert result["service_provider"] == ""

    def test_strips_diagnoses(self):
        result = project_encounter(self.FULL_ENCOUNTER)
        assert "diagnosis" not in result
        assert "reasonCode" not in result

    def test_handles_missing_fields(self):
        minimal = {"resourceType": "Encounter", "id": "enc-002", "status": "planned"}
        result = project_encounter(minimal)
        assert result["status"] == "planned"
        assert result["type"] == ""
        assert result["date"] == ""
        assert result["practitioner_name"] == ""
        assert result["service_provider"] == ""

    def test_pf_encounter_shape(self):
        """PF returns encounters with serviceProvider and data-absent-reason type."""
        pf_enc = {
            "resourceType": "Encounter",
            "id": "enc-pf",
            "status": "in-progress",
            "class": {"code": "unknown", "display": "unknown"},
            "type": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/data-absent-reason", "code": "unknown", "display": "Unknown"}], "text": "Unknown"}],
            "serviceProvider": {"reference": "Organization/org-1", "display": "Practice Fusion Partner Sandbox"},
            "subject": {"reference": "Patient/p-1", "display": "Durve, Mohit"},
        }
        result = project_encounter(pf_enc)
        assert result["service_provider"] == "Practice Fusion Partner Sandbox"
        assert result["type"] == ""  # "Unknown" filtered out


# ---------------------------------------------------------------------------
# DocumentReference
# ---------------------------------------------------------------------------

class TestDocumentReferenceProjection:
    FULL_DOC = {
        "resourceType": "DocumentReference",
        "id": "doc-001",
        "status": "current",
        "type": {
            "coding": [{"system": "http://loinc.org", "code": "34117-2", "display": "History and physical note"}],
            "text": "H&P Note",
        },
        "date": "2026-05-19T11:00:00Z",
        "description": "Annual physical exam documentation",
        "author": [{"display": "Dr. Sarah Chen"}],
        "content": [
            {"attachment": {"contentType": "application/pdf", "url": "https://example.com/doc.pdf"}}
        ],
    }

    def test_extracts_safe_fields(self):
        result = project_document_reference(self.FULL_DOC)
        assert result["status"] == "current"
        assert result["type"] == "H&P Note"
        assert result["date"] == "2026-05-19"
        assert result["description"] == "Annual physical exam documentation"
        assert result["author"] == "Dr. Sarah Chen"

    def test_strips_content(self):
        result = project_document_reference(self.FULL_DOC)
        assert "content" not in result
        assert "url" not in result

    def test_handles_missing_fields(self):
        minimal = {"resourceType": "DocumentReference", "id": "doc-002", "status": "entered-in-error"}
        result = project_document_reference(minimal)
        assert result["status"] == "entered-in-error"
        assert result["type"] == ""
        assert result["date"] == ""
        assert result["description"] == ""
        assert result["author"] == ""


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------

class TestObservationProjection:
    FULL_OBS = {
        "resourceType": "Observation",
        "id": "obs-001",
        "status": "final",
        "category": [
            {
                "coding": [
                    {"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory", "display": "Laboratory"}
                ]
            }
        ],
        "code": {
            "coding": [{"system": "http://loinc.org", "code": "6690-2", "display": "Leukocytes [#/volume] in Blood"}],
            "text": "WBC",
        },
        "effectiveDateTime": "2026-05-20T10:30:00Z",
        "valueQuantity": {"value": 7.2, "unit": "10*3/uL"},
        "referenceRange": [{"low": {"value": 4.5}, "high": {"value": 11.0}, "text": "4.5-11.0 10*3/uL"}],
        "interpretation": [{"coding": [{"code": "N", "display": "Normal"}]}],
    }

    def test_extracts_safe_fields(self):
        result = project_observation(self.FULL_OBS)
        assert result["status"] == "final"
        assert result["code_display"] == "Leukocytes [#/volume] in Blood"
        assert result["effective_date"] == "2026-05-20"
        assert result["category"] == "Laboratory"

    def test_strips_values_and_ranges(self):
        result = project_observation(self.FULL_OBS)
        assert "value" not in result
        assert "valueQuantity" not in result
        assert "referenceRange" not in result
        assert "interpretation" not in result

    def test_handles_missing_fields(self):
        minimal = {"resourceType": "Observation", "id": "obs-002", "status": "registered"}
        result = project_observation(minimal)
        assert result["status"] == "registered"
        assert result["code_display"] == ""
        assert result["effective_date"] == ""
        assert result["category"] == ""


# ---------------------------------------------------------------------------
# AllergyIntolerance
# ---------------------------------------------------------------------------

class TestAllergyIntoleranceProjection:
    FULL = {
        "resourceType": "AllergyIntolerance",
        "id": "ai-1",
        "clinicalStatus": {"coding": [{"code": "active", "display": "Active"}]},
        "type": "allergy",
        "criticality": "high",
        "code": {"coding": [{"display": "Penicillin"}], "text": "Penicillin"},
        "onsetDateTime": "2020-03-15",
        "recorder": {"display": "Dr. Smith"},
        "reaction": [{"manifestation": [{"text": "Hives"}], "severity": "severe"}],
    }

    def test_extracts_safe_fields(self):
        result = project_allergy_intolerance(self.FULL)
        assert result["substance"] == "Penicillin"
        assert result["clinical_status"] == "Active"
        assert result["type"] == "allergy"
        assert result["criticality"] == "high"
        assert result["onset_date"] == "2020-03-15"
        assert result["recorder"] == "Dr. Smith"

    def test_strips_reaction_details(self):
        result = project_allergy_intolerance(self.FULL)
        assert "reaction" not in result
        assert "manifestation" not in result

    def test_handles_missing_fields(self):
        minimal = {"resourceType": "AllergyIntolerance", "id": "ai-2"}
        result = project_allergy_intolerance(minimal)
        assert result["substance"] == ""
        assert result["clinical_status"] == ""


# ---------------------------------------------------------------------------
# Condition
# ---------------------------------------------------------------------------

class TestConditionProjection:
    FULL = {
        "resourceType": "Condition",
        "id": "cond-1",
        "clinicalStatus": {"coding": [{"code": "active", "display": "Active"}], "text": "Active"},
        "category": [{"coding": [{"display": "Problem List Item"}]}],
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": "38341003", "display": "Hypertension"}], "text": "Essential hypertension"},
        "onsetDateTime": "2022-01-10",
        "evidence": [{"detail": [{"reference": "Observation/bp-1"}]}],
    }

    def test_extracts_safe_fields(self):
        result = project_condition(self.FULL)
        assert result["code_display"] == "Hypertension"
        assert result["clinical_status"] == "Active"
        assert result["category"] == "Problem List Item"
        assert result["onset_date"] == "2022-01-10"

    def test_strips_codes_and_evidence(self):
        result = project_condition(self.FULL)
        assert "evidence" not in result
        assert "code" not in result  # raw code object stripped

    def test_pf_overloaded_code_text(self):
        """PF stuffs metadata into code.text — should use coding.display instead."""
        pf_cond = {
            "resourceType": "Condition",
            "id": "cond-pf",
            "code": {
                "text": "Nicotine dependence; 2026-03-11; not applicable; active; Dr Robert Killian; Practice Fusion Partner Sandbox; 3/11/2026",
                "coding": [
                    {"system": "http://snomed.info/sct", "code": "56294008", "display": "Nicotine dependence"},
                ],
            },
            "clinicalStatus": {"coding": [{"code": "active", "display": "Active"}]},
        }
        result = project_condition(pf_cond)
        assert result["code_display"] == "Nicotine dependence"
        assert ";" not in result["code_display"]


# ---------------------------------------------------------------------------
# Immunization
# ---------------------------------------------------------------------------

class TestImmunizationProjection:
    FULL = {
        "resourceType": "Immunization",
        "id": "imm-1",
        "status": "completed",
        "vaccineCode": {"coding": [{"display": "Influenza vaccine"}], "text": "Flu Shot 2025-2026"},
        "occurrenceDateTime": "2025-10-01",
        "lotNumber": "ABC123",
        "performer": [{"actor": {"display": "Dr. Jones"}}],
        "site": {"text": "Left arm"},
        "route": {"text": "Intramuscular"},
    }

    def test_extracts_safe_fields(self):
        result = project_immunization(self.FULL)
        assert result["vaccine_name"] == "Flu Shot 2025-2026"
        assert result["date"] == "2025-10-01"
        assert result["status"] == "completed"
        assert result["performer_name"] == "Dr. Jones"
        assert result["lot_number"] == "ABC123"

    def test_strips_site_and_route(self):
        result = project_immunization(self.FULL)
        assert "site" not in result
        assert "route" not in result


# ---------------------------------------------------------------------------
# Procedure
# ---------------------------------------------------------------------------

class TestProcedureProjection:
    FULL = {
        "resourceType": "Procedure",
        "id": "proc-1",
        "status": "completed",
        "code": {"coding": [{"display": "Colonoscopy"}], "text": "Screening colonoscopy"},
        "performedDateTime": "2026-03-10",
        "performer": [{"actor": {"display": "Dr. Wilson"}}],
        "complication": [{"text": "None"}],
        "outcome": {"text": "Normal"},
        "bodySite": [{"coding": [{"display": "Colon"}]}],
    }

    def test_extracts_safe_fields(self):
        result = project_procedure(self.FULL)
        assert result["code_display"] == "Colonoscopy"
        assert result["date"] == "2026-03-10"
        assert result["status"] == "completed"
        assert result["performer_name"] == "Dr. Wilson"

    def test_strips_clinical_details(self):
        result = project_procedure(self.FULL)
        assert "complication" not in result
        assert "outcome" not in result
        assert "bodySite" not in result


# ---------------------------------------------------------------------------
# CarePlan
# ---------------------------------------------------------------------------

class TestCarePlanProjection:
    FULL = {
        "resourceType": "CarePlan",
        "id": "cp-1",
        "status": "active",
        "category": [{"coding": [{"display": "Longitudinal"}], "text": "Longitudinal care plan"}],
        "description": "Manage hypertension with lifestyle changes",
        "period": {"start": "2026-01-01", "end": "2026-12-31"},
        "activity": [{"detail": {"description": "Daily blood pressure monitoring"}}],
        "addresses": [{"reference": "Condition/cond-1"}],
    }

    def test_extracts_safe_fields(self):
        result = project_care_plan(self.FULL)
        assert result["status"] == "active"
        assert result["category"] == "Longitudinal"
        assert result["description"] == "Manage hypertension with lifestyle changes"
        assert result["period_start"] == "2026-01-01"
        assert result["period_end"] == "2026-12-31"

    def test_strips_activity_and_addresses(self):
        result = project_care_plan(self.FULL)
        assert "activity" not in result
        assert "addresses" not in result


# ---------------------------------------------------------------------------
# CareTeam
# ---------------------------------------------------------------------------

class TestCareTeamProjection:
    FULL = {
        "resourceType": "CareTeam",
        "id": "ct-1",
        "status": "active",
        "participant": [
            {"member": {"display": "Dr. Sarah Chen"}, "role": [{"text": "Primary Care Physician"}]},
            {"member": {"display": "Nurse Jane"}, "role": [{"coding": [{"display": "Registered Nurse"}]}]},
        ],
    }

    def test_extracts_participants(self):
        result = project_care_team(self.FULL)
        assert result["status"] == "active"
        assert len(result["participants"]) == 2
        assert result["participants"][0]["name"] == "Dr. Sarah Chen"
        assert result["participants"][0]["role"] == "Primary Care Physician"
        assert result["participants"][1]["name"] == "Nurse Jane"
        assert result["participants"][1]["role"] == "Registered Nurse"

    def test_handles_empty_participants(self):
        minimal = {"resourceType": "CareTeam", "id": "ct-2", "status": "proposed"}
        result = project_care_team(minimal)
        assert result["participants"] == []


# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------

class TestGoalProjection:
    FULL = {
        "resourceType": "Goal",
        "id": "goal-1",
        "lifecycleStatus": "active",
        "description": {"text": "Lower blood pressure to below 130/80"},
        "startDate": "2026-01-15",
        "target": [{"dueDate": "2026-07-15"}],
        "achievementStatus": {"coding": [{"display": "In Progress"}]},
    }

    def test_extracts_safe_fields(self):
        result = project_goal(self.FULL)
        assert result["description"] == "Lower blood pressure to below 130/80"
        assert result["status"] == "active"
        assert result["start_date"] == "2026-01-15"
        assert result["target_date"] == "2026-07-15"

    def test_strips_achievement_detail(self):
        result = project_goal(self.FULL)
        assert "achievementStatus" not in result

    def test_handles_missing_fields(self):
        minimal = {"resourceType": "Goal", "id": "goal-2", "lifecycleStatus": "proposed"}
        result = project_goal(minimal)
        assert result["status"] == "proposed"
        assert result["description"] == ""
        assert result["target_date"] == ""


# ---------------------------------------------------------------------------
# project_resource dispatcher
# ---------------------------------------------------------------------------

class TestProjectResource:
    def test_dispatches_to_correct_projection(self):
        dr = {"resourceType": "DiagnosticReport", "id": "dr-x", "status": "final"}
        result = project_resource(dr)
        assert "status" in result
        assert "code_display" in result

    def test_rejects_unknown_resource_type(self):
        with pytest.raises(ValueError, match="Unsupported resource type"):
            project_resource({"resourceType": "Coverage", "id": "c-1"})

    def test_rejects_missing_resource_type(self):
        with pytest.raises(ValueError, match="Unsupported resource type"):
            project_resource({"id": "x"})
