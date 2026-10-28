# KoboCollect Mobile Integration Roadmap

**Purpose:** Enable offline mobile data collection using KoboCollect-compatible forms built in OpSyn Form Builder.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  OpSyn Form Builder (Web)                                    │
│  - Design forms visually                                     │
│  - Define validation rules                                   │
│  - Configure mobile deployment                               │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ Export as XForm
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  XForm Generation Service                                    │
│  - Convert FormSchema to XLSForm/XForm XML                   │
│  - Map OpSyn field types to ODK types                        │
│  - Include validation rules and constraints                  │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ Push to Mobile
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  Mobile App (KoboCollect / Custom ODK)                       │
│  - Download forms over WiFi/cellular                         │
│  - Collect data offline in field                             │
│  - GPS, photos, signatures                                   │
│  - Store locally until sync                                  │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ Sync when online
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  OpSyn Sync API                                              │
│  - Receive submissions from mobile                           │
│  - Validate against schema version                           │
│  - Insert into dynamic tables                                │
│  - Handle conflicts and duplicates                           │
└─────────────────────────────────────────────────────────────┘
```

---

## Phase 1: XForm Export (Week 1-2)

### Goal
Enable "Export to Mobile" button that generates KoboCollect-compatible XForm from any FormSchema.

### Components

**1. XForm Generator Service**

`app/modules/form_builder/xform_generator.py`

```python
class XFormGenerator:
    """Converts OpSyn FormSchema to XLSForm/XForm XML"""
    
    def generate_xlsform(self, schema_id: UUID) -> dict:
        """
        Generates XLSForm (3-sheet Excel format) from FormSchema.
        Returns: {survey: [], choices: [], settings: {}}
        """
        schema = await self._get_schema(schema_id)
        fields = await self._get_fields(schema_id)
        
        survey_sheet = []
        choices_sheet = []
        
        for field in fields:
            row = self._map_field_to_xlsform_row(field)
            survey_sheet.append(row)
            
            if field.field_type in ['enum', 'multiselect', 'radio']:
                choices = self._generate_choices(field)
                choices_sheet.extend(choices)
        
        return {
            'survey': survey_sheet,
            'choices': choices_sheet,
            'settings': {
                'form_title': schema.name,
                'form_id': str(schema.id),
                'version': schema.current_version,
            }
        }
    
    def generate_xform_xml(self, schema_id: UUID) -> str:
        """
        Generates XForm XML from FormSchema.
        Returns: XML string compatible with ODK/KoboCollect
        """
        xlsform = self.generate_xlsform(schema_id)
        return self._convert_xlsform_to_xml(xlsform)
```

**2. Field Type Mapping**

| OpSyn Type | XLSForm Type | ODK Widget |
|------------|-------------|-----------|
| string | text | default |
| text | text | multiline |
| integer | integer | default |
| float | decimal | default |
| boolean | select_one yes_no | minimal |
| date | date | default |
| datetime | dateTime | default |
| email | text | default (constraint: email) |
| phone | text | default (constraint: phone) |
| enum | select_one {list_name} | minimal |
| multiselect | select_multiple {list_name} | minimal |
| radio | select_one {list_name} | horizontal-compact |
| coordinates | geopoint | default (uses GPS) |
| image | image | default (camera) |
| signature | image | signature |
| file | file | default |

**3. API Endpoint**

```python
@router.get("/schemas/{schema_id}/export/xform")
async def export_to_xform(
    schema_id: UUID,
    format: str = Query("xml", regex="^(xml|xlsform)$"),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user)
):
    """Export form as XForm XML or XLSForm for mobile deployment."""
    
    generator = XFormGenerator(db)
    
    if format == "xlsform":
        xlsform = await generator.generate_xlsform(schema_id)
        # Convert to Excel file
        excel_file = create_xlsform_excel(xlsform)
        return FileResponse(
            excel_file,
            filename=f"{schema.machine_name}_xlsform.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        xform_xml = await generator.generate_xform_xml(schema_id)
        return Response(
            content=xform_xml,
            media_type="application/xml",
            headers={
                "Content-Disposition": f"attachment; filename={schema.machine_name}.xml"
            }
        )
```

---

## Phase 2: Mobile Sync API (Week 3-4)

### Goal
Accept form submissions from mobile devices and insert into dynamic tables.

### Components

**1. Submission Endpoint**

```python
@router.post("/mobile/submit")
async def mobile_submission(
    submission: MobileSubmissionPayload,
    api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db)
):
    """
    Receive form submission from mobile app.
    
    Payload format:
    {
        "form_id": "uuid",
        "form_version": 2,
        "instance_id": "uuid_v4",
        "submitted_at": "2026-09-27T16:00:00Z",
        "data": {
            "field_key_1": "value_1",
            "field_key_2": "value_2",
            ...
        },
        "attachments": [
            {"field_key": "photo", "filename": "img.jpg", "data": "base64..."}
        ]
    }
    """
    
    # Authenticate API key
    tenant = await authenticate_mobile_api_key(api_key)
    
    # Get schema and version
    schema = await get_schema_by_id(submission.form_id)
    version = await get_schema_version(schema.id, submission.form_version)
    
    if not version:
        raise HTTPException(400, "Form version not found or outdated")
    
    # Validate submission against schema
    validation_result = await validate_submission(
        submission.data,
        version.field_snapshot
    )
    
    if not validation_result.is_valid:
        raise HTTPException(422, validation_result.errors)
    
    # Handle file attachments
    attachment_paths = await save_mobile_attachments(
        submission.attachments,
        tenant.id
    )
    
    # Insert into dynamic table
    table_name = f"tenant_{tenant.id}_{schema.machine_name}_data"
    await insert_into_dynamic_table(
        table_name=table_name,
        data=submission.data,
        attachments=attachment_paths,
        submitted_by=None,  # Mobile submissions may be anonymous
        submitted_at=submission.submitted_at
    )
    
    return {"success": True, "instance_id": submission.instance_id}
```

**2. Conflict Resolution**

```python
class MobileConflictResolver:
    """Handle duplicate submissions and offline edits."""
    
    async def check_duplicate(
        self,
        instance_id: str,
        form_id: UUID
    ) -> bool:
        """Check if instance_id already submitted."""
        existing = await self.db.execute(
            select(MobileSubmissionLog)
            .where(
                MobileSubmissionLog.instance_id == instance_id,
                MobileSubmissionLog.form_id == form_id
            )
        )
        return existing.scalar_one_or_none() is not None
    
    async def resolve_conflict(
        self,
        existing_data: dict,
        new_data: dict,
        strategy: str = "last_write_wins"
    ) -> dict:
        """
        Resolve conflicts when same record edited offline by multiple users.
        
        Strategies:
        - last_write_wins: Most recent submission wins
        - merge_fields: Merge non-conflicting fields
        - manual_review: Flag for admin review
        """
        if strategy == "last_write_wins":
            return new_data
        elif strategy == "merge_fields":
            return self._merge_non_conflicting_fields(existing_data, new_data)
        else:
            return await self._queue_for_manual_review(existing_data, new_data)
```

---

## Phase 3: Mobile API Key Management (Week 5)

### Goal
Secure mobile apps with per-device or per-user API keys.

### Components

**1. Mobile API Keys Table**

```sql
CREATE TABLE mobile_api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key_hash VARCHAR(64) NOT NULL,  -- SHA256 of actual key
    key_prefix VARCHAR(8) NOT NULL,  -- First 8 chars for identification
    
    -- Metadata
    label VARCHAR(100),  -- "Field Tech Team A Phone 1"
    assigned_to UUID REFERENCES users(id) ON DELETE SET NULL,
    device_info JSONB,  -- {device_id, model, os_version}
    
    -- Permissions
    allowed_forms UUID[],  -- NULL = all forms, or specific form IDs
    
    -- Status
    is_active BOOLEAN NOT NULL DEFAULT true,
    expires_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL
);
```

**2. API Key Generation**

```python
@router.post("/mobile/api-keys")
async def generate_mobile_api_key(
    body: CreateAPIKeyRequest,
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("mobile.manage"))
):
    """Generate new API key for mobile device."""
    
    # Generate secure random key
    api_key = secrets.token_urlsafe(32)  # e.g., "opsyn_mobile_xY7zK..."
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    key_prefix = api_key[:8]
    
    key_record = MobileAPIKey(
        tenant_id=caller.tenant_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        label=body.label,
        assigned_to=body.assigned_to,
        allowed_forms=body.allowed_forms,
        expires_at=body.expires_at,
        created_by=caller.id
    )
    db.add(key_record)
    await db.commit()
    
    return {
        "api_key": api_key,  # ONLY shown once
        "key_prefix": key_prefix,
        "expires_at": body.expires_at,
        "message": "Store this key securely. It won't be shown again."
    }
```

---

## Phase 4: Offline Sync Strategy (Week 6)

### Goal
Handle intermittent connectivity and large submission backlogs.

### Components

**1. Batch Submission**

```python
@router.post("/mobile/submit/batch")
async def batch_mobile_submission(
    submissions: list[MobileSubmissionPayload],
    api_key: str = Header(...),
    db: AsyncSession = Depends(get_db)
):
    """Accept multiple form submissions in one request."""
    
    results = []
    
    for submission in submissions:
        try:
            result = await process_single_submission(submission, api_key, db)
            results.append({"instance_id": submission.instance_id, "status": "success"})
        except Exception as e:
            results.append({
                "instance_id": submission.instance_id,
                "status": "failed",
                "error": str(e)
            })
    
    return {
        "total": len(submissions),
        "success": sum(1 for r in results if r["status"] == "success"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "results": results
    }
```

**2. Incremental Sync**

```python
@router.get("/mobile/sync/check")
async def check_sync_status(
    device_id: str = Query(...),
    last_sync: datetime = Query(...),
    api_key: str = Header(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Check what needs to sync since last successful sync.
    Returns: List of form updates and pending submissions.
    """
    
    tenant = await authenticate_mobile_api_key(api_key)
    
    # Check for form schema updates
    updated_forms = await db.execute(
        select(FormSchema)
        .where(
            FormSchema.tenant_id == tenant.id,
            FormSchema.updated_at > last_sync
        )
    )
    
    # Check for pending submissions on device
    # (tracked in mobile_submission_log)
    
    return {
        "forms_to_update": [form.id for form in updated_forms.scalars()],
        "submissions_received": [],  # List of instance_ids already received
        "server_time": datetime.utcnow()
    }
```

---

## Phase 5: Mobile Form Assignment (Week 7)

### Goal
Assign specific forms to specific users/roles for mobile deployment.

### Components

**1. Mobile Form Assignment Table**

```sql
CREATE TABLE mobile_form_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    form_schema_id UUID NOT NULL REFERENCES form_schemas(id) ON DELETE CASCADE,
    
    -- Assignment target
    assigned_to_user UUID REFERENCES users(id) ON DELETE CASCADE,
    assigned_to_role VARCHAR(50),
    assigned_to_department UUID REFERENCES departments(id) ON DELETE CASCADE,
    
    -- Constraints
    required BOOLEAN NOT NULL DEFAULT false,  -- Must complete X submissions
    target_count INTEGER,  -- Target number of submissions
    deadline TIMESTAMPTZ,
    
    -- Geo-fencing (optional)
    allowed_regions JSONB,  -- [{name, lat, lng, radius_km}]
    
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL
);
```

**2. User Form List Endpoint**

```python
@router.get("/mobile/my-forms")
async def get_user_assigned_forms(
    api_key: str = Header(...),
    db: AsyncSession = Depends(get_db)
):
    """Get list of forms assigned to authenticated mobile user."""
    
    user, tenant = await authenticate_mobile_user(api_key)
    
    # Get directly assigned forms
    directly_assigned = await db.execute(
        select(FormSchema)
        .join(MobileFormAssignment)
        .where(
            MobileFormAssignment.assigned_to_user == user.id,
            MobileFormAssignment.is_active == True
        )
    )
    
    # Get role-based assigned forms
    role_assigned = await db.execute(
        select(FormSchema)
        .join(MobileFormAssignment)
        .where(
            MobileFormAssignment.assigned_to_role.in_(user.roles),
            MobileFormAssignment.is_active == True
        )
    )
    
    # Combine and deduplicate
    forms = list(set(directly_assigned.scalars()) | set(role_assigned.scalars()))
    
    return {
        "forms": [
            {
                "id": form.id,
                "name": form.name,
                "version": form.current_version,
                "download_url": f"/api/v1/form-builder/schemas/{form.id}/export/xform",
                "required": assignment.required,
                "target_count": assignment.target_count,
                "deadline": assignment.deadline
            }
            for form in forms
        ]
    }
```

---

## Phase 6: Data Quality & Validation (Week 8)

### Goal
Ensure mobile submissions meet quality standards before acceptance.

### Components

**1. Server-Side Validation**

```python
class MobileSubmissionValidator:
    """Validate mobile submissions against schema rules."""
    
    async def validate(
        self,
        data: dict,
        field_snapshot: list[dict]
    ) -> ValidationResult:
        """Comprehensive validation of mobile submission."""
        
        errors = []
        
        for field_def in field_snapshot:
            field_key = field_def['field_key']
            value = data.get(field_key)
            
            # Required field check
            if field_def['is_required'] and not value:
                errors.append(f"{field_key} is required")
            
            # Type validation
            if value and not self._validate_type(value, field_def['field_type']):
                errors.append(f"{field_key} has invalid type")
            
            # Custom validation rules
            if field_def.get('validation_rules'):
                rule_errors = self._apply_validation_rules(
                    value,
                    field_def['validation_rules']
                )
                errors.extend(rule_errors)
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors
        )
```

**2. GPS Validation**

```python
def validate_gps_coordinates(coords: dict, allowed_regions: list) -> bool:
    """Validate GPS coordinates are within allowed regions."""
    
    if not allowed_regions:
        return True  # No geo-fencing
    
    point = (coords['latitude'], coords['longitude'])
    
    for region in allowed_regions:
        center = (region['lat'], region['lng'])
        radius_km = region['radius_km']
        
        if haversine_distance(point, center) <= radius_km:
            return True
    
    return False
```

---

## Phase 7: Reporting & Analytics (Week 9)

### Goal
Visualize mobile data collection progress and quality metrics.

### Metrics to Track

- Forms deployed vs. forms completed
- Submissions per user/device/day
- Offline time before sync
- Data quality scores
- Geographic distribution of submissions
- Average submission duration

---

## Technology Stack

**Mobile App Options:**

1. **KoboCollect (ODK-based)** - Open source, mature, offline-first
2. **ODK Collect** - Reference implementation
3. **Custom Flutter App** - Full control, branded experience
4. **Custom React Native App** - Cross-platform, web code reuse

**XForm Libraries:**
- `pyxform` (Python) - Convert XLSForm to XForm XML
- `xform-test` - Validate XForm XML

**File Storage:**
- AWS S3 / MinIO for attachments (photos, signatures)
- Separate bucket per tenant

---

## Security Considerations

1. **API Key Rotation:** Expire old keys after 90 days
2. **Rate Limiting:** Max 1000 submissions per device per day
3. **Attachment Scanning:** Virus scan uploaded files
4. **Encrypted Storage:** Encrypt sensitive form data at rest
5. **Audit Trail:** Log all mobile submissions with device_id

---

## Timeline Summary

| Phase | Weeks | Deliverable |
|-------|-------|------------|
| 1 | 1-2 | XForm export from Form Builder |
| 2 | 3-4 | Mobile sync API |
| 3 | 5 | API key management |
| 4 | 6 | Offline sync strategy |
| 5 | 7 | Form assignment system |
| 6 | 8 | Data quality validation |
| 7 | 9 | Reporting dashboard |

**Total:** 9 weeks to production-ready mobile integration

---

## Success Metrics

- **Form Export:** 100% of form types exportable to XForm
- **Sync Reliability:** 99.9% successful sync rate
- **Offline Duration:** Support 7+ days offline operation
- **Submission Speed:** < 2 seconds per submission upload
- **Data Quality:** > 95% of submissions pass validation on first try

---

## Next Steps

1. Finalize mobile app choice (KoboCollect vs. custom)
2. Set up XForm testing environment
3. Begin Phase 1 implementation
4. Recruit beta testers with field teams
