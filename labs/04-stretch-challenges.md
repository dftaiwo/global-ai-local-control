# Optional stretch challenges and discussion prompts

**Technical challenge A — Data minimisation**: Replace raw payment IDs sent to the model with short-lived opaque references. Maintain the mapping server-side, signed or bound to user/session.

**Technical challenge B — Egress policy**: Add an `allowed_model_regions` configuration and reject an inference profile whose known destination Regions do not match the organisation's approved data-transfer policy. Do not infer destination solely from the source Region.

**Technical challenge C — Intent/role separation**: In a real system, replace the demo role dropdown and CLI role flag with an authenticated principal derived from an IdP token. Introduce resource-level authorisation and multi-tenancy tests.

**Technical challenge D — Observability**: Log tool outcomes and request metadata while ensuring tracing, APM, exception reports and audit entries do not record raw customer data.

**Discussion**: Which of these belongs in the model prompt, which in the tool gateway, which in IAM/network controls, and which in governance/legal review?
