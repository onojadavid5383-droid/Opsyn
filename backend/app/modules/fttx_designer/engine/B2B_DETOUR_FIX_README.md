# B2B Graph Detour Fix - Implementation Guide

## Problem Summary

Your FTTx design is failing with the error:
```
[B2B_GRAPH_DETOUR] 7 box-to-box route(s) have implausible detours
```

This indicates **cuts in the routing graph** - road segments that don't properly connect at intersections. When the router tries to find a path between two nearby devices, it's forced to take long detours around these "invisible walls."

### Your Specific Cases

The most severe detours in your design:
- **B2B_FDT-44A_03_FAT-44A-02_FAT-44A-03**: 209.43x detour (routed 209m for 1m straight-line)
- **B2B_FDT-16B_01_FDT-16_FAT-16B-01**: 15.13x detour (routed 578m for 38m straight-line)
- **B2B_FDT-16B_02_FAT-16B-01_FAT-16B-02**: 14.85x detour (routed 579m for 39m straight-line)

These extreme ratios (>2.5x threshold) mean the road network topology has serious breaks.

## What Was Implemented

### 1. New Module: `noding_repair.py`

Created a diagnostic toolkit that:
- Cross-references B2B detours with road graph noding defects
- Identifies the exact coordinates of topology breaks
- Generates repair layers for QGIS inspection
- Provides step-by-step repair instructions

### 2. Enhanced Pipeline Integration

Modified `pipeline.py` to automatically:
- Diagnose B2B detours when they're detected
- Generate a `noding_defects` output layer
- Log detailed repair instructions before failing
- Export the defect locations for field inspection

### 3. Defect Classification

The system identifies two types of noding defects:

**T_UNNODED** (Critical - primary cause of detours):
- A line endpoint lies on another line's interior with NO vertex there
- Only line noding (Vector > Geometry > Node Lines in QGIS) fixes this
- These create "invisible walls" in the routing graph

**NEAR_MISS** (Less critical):
- Line endpoints are very close but don't exactly touch
- Usually healable by MASTER_GRAPH_TOPOLOGY_TOLERANCE
- Can be fixed with snap geometries or manual adjustment

## How to Use the Fix

### Step 1: Run Your Design

When you run the FTTx design and B2B detours are detected, the pipeline now:

1. **Logs the diagnosis**:
   ```
   [B2B Detour Root Cause Diagnosis]
   [B2B-DETOUR-DIAGNOSIS] 7/7 suspects traced to noding defects
   [B2B-DETOUR-DIAGNOSIS] Road graph has 15 T_UNNODED + 8 NEAR_MISS defects
   [B2B-DETOUR-DIAGNOSIS] Top repair priorities:
       T_UNNODED at POINT(x y) gap=0.5m affects 3 B2B cable(s)
       ...
   ```

2. **Exports a repair layer**: `noding_defects` in your output layers
3. **Provides repair instructions** in the log

### Step 2: Load the Noding Defects Layer in QGIS

The `noding_defects` layer contains point features at each topology break with attributes:
- `defect_type`: T_UNNODED or NEAR_MISS
- `gap_m`: Distance between the endpoints
- `vertex_gap_m`: Gap to nearest vertex
- `wkt`: Coordinates ready for QGIS locator bar
- `fid`, `other_fid`: The road feature IDs involved

### Step 3: Prioritize Repairs

Focus on defects that affect multiple B2B cables first (shown in the diagnosis log).

The coordinates from your error message map to specific defects:
- Check near FDT-44A, FAT-44A-02, FAT-44A-03
- Check near FDT-16B, FAT-16B-01, FAT-16B-02
- Check near FDT-16A, FAT-16A-02, FAT-16A-03

### Step 4: Repair the Road Layer

#### For T_UNNODED Defects (Most Important):

**Option A - Automatic Noding**:
1. In QGIS: Vector menu > Geometry Tools > Node Lines
2. Input: Your roads layer
3. Output: Save as `roads_noded`
4. Replace your original roads layer with the noded version

**Option B - Manual Repair**:
1. Enable editing on your roads layer
2. Zoom to each defect point (paste WKT coordinate into QGIS locator)
3. Use the Node Tool to add a vertex at the exact defect location
4. Ensure both road segments share that exact vertex
5. Save edits

#### For NEAR_MISS Defects:

**Option A - Snap Geometries**:
1. Vector menu > Geometry Tools > Snap Geometries to Layer
2. Input: Roads layer
3. Reference: Roads layer
4. Tolerance: 2.0m (or your NODING_AUDIT_GAP_TOL)

**Option B - Manual Snap**:
1. Enable snapping (magnet icon) with 2m tolerance
2. Move line endpoints to snap to nearby segments

### Step 5: Verify Device Anchors

Sometimes the issue isn't the road layer but device placement:

1. Check that FAT/FDT devices are placed ON road centerlines
2. Devices in parking lots or behind buildings may snap to disconnected roads
3. Review devices mentioned in the error messages
4. Move any misplaced devices to proper road locations

### Step 6: Re-run the Design

After repairing:
1. Save your corrected roads layer
2. Re-run the FTTx design
3. Check the `[NODING-AUDIT]` log line - should show fewer defects
4. B2B detour ratios should drop below 2.5x
5. If detours persist, check the new diagnosis output for remaining issues

## Configuration Options

### Adjust Detour Thresholds (if needed)

In `config.py`:
```python
B2B_DETOUR_RATIO_LIMIT = 2.5  # Routes >2.5x straight-line are flagged
B2B_DETOUR_ABS_LIMIT = 120.0  # Only check routes longer than 120m
```

### Enable Road Noding (already enabled)

In `config.py`:
```python
NODE_ROADS_FOR_ROUTING = True  # Automatic noding before routing
```

### Tolerance Settings

In `config.py`:
```python
NODING_AUDIT_GAP_TOL = 2.0              # Gap tolerance for defect detection
MASTER_GRAPH_TOPOLOGY_TOLERANCE = 1.0   # Snap tolerance for graph building
```

## Understanding the Diagnosis Output

### Sample Diagnosis Log:

```
[B2B-DETOUR-DIAGNOSIS] 7/7 suspects traced to noding defects
```
- All 7 B2B detours are linked to road topology breaks

```
[B2B-DETOUR-DIAGNOSIS] Road graph has 15 T_UNNODED + 8 NEAR_MISS defects
```
- 15 critical breaks (T_UNNODED) need manual or automatic noding
- 8 minor gaps (NEAR_MISS) are usually healable automatically

```
Top repair priorities:
    T_UNNODED at POINT(x y) gap=0.5m affects 3 B2B cable(s)
```
- This specific junction break is causing detours for 3 different cables
- Fix this one first for maximum impact

## Repair Instructions Generated by the System

The system automatically generates detailed QGIS repair instructions including:
1. How to open and inspect the repair layer
2. Prioritized list of defects by impact
3. Step-by-step repair strategies for each defect type
4. Validation steps after repair

These instructions appear in your log output after:
```
=== QGIS Road Graph Noding Repair Instructions ===
```

## Technical Details

### What Causes Noding Defects?

1. **CAD/GIS Import Issues**: Lines that appear connected may not share vertices
2. **Digitization Errors**: Manual line drawing without proper snapping
3. **Layer Merging**: Combining multiple sources without topology validation
4. **Coordinate Precision**: Rounding errors in coordinate transformations

### How the Fix Works

1. **Detection**: `audit_road_layer_noding()` scans every line endpoint
2. **Classification**: Determines if nearby segments share vertices
3. **Cross-Reference**: Links detours to specific noding defects
4. **Prioritization**: Ranks defects by number of affected B2B cables
5. **Export**: Creates a point layer marking each defect location
6. **Guidance**: Generates human-readable repair instructions

### Performance Impact

- Noding audit adds ~2-5 seconds to pipeline runtime
- Diagnosis only runs when detours are actually detected
- No impact on successful designs without topology issues

## Troubleshooting

### "Noding defects layer is empty"
- Your road topology is actually fine
- Detours may be caused by device anchor positions instead
- Check device placement on the road network

### "Still getting detours after noding"
- Verify the noded layer is being used for routing
- Check that all defects were actually repaired
- May need multiple repair passes for complex issues
- Consider manual inspection of specific problem junctions

### "Diagnosis failed" message
- Non-critical - validation still runs
- Check logs for the specific error
- May indicate corrupted geometries in road layer

## Files Modified

1. **`noding_repair.py`** (NEW): Diagnostic and repair toolkit
2. **`pipeline.py`**: Integrated diagnosis into validation flow
3. **`config.py`**: Added noding_defects to output layer schemas

## Next Steps

1. Run your design to see the new diagnostic output
2. Export and inspect the `noding_defects` layer
3. Repair road topology as prioritized by the diagnosis
4. Re-run until all B2B detours are below threshold

---

**Need Help?** Check the log output for specific coordinates and defect types. Each defect includes WKT coordinates you can paste directly into QGIS to jump to that location.
