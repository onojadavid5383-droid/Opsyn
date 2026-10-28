-- ============================================================
-- OPSYN — tests/integration/network_gis_seed.sql
-- Seed rows for test_network_gis_db.py: uploaded FTTH assets around
-- Allen Avenue / Toyin Street, Ikeja, in the development tenant.
-- Load into a scratch copy of the database BEFORE migrating to 0087, so
-- the migration's backfill is what creates the net_assets rows:
--
--   createdb -T opsyn opsyn_gis_test
--   psql -d opsyn_gis_test -v t=00000000-0000-0000-0000-000000000001 -f network_gis_seed.sql
--   DATABASE_URL=…/opsyn_gis_test alembic upgrade head
--
-- SPL-OLD-99 is soft-deleted and must NOT be mirrored.
-- ============================================================

INSERT INTO olts (id, tenant_id, name, location_description, number_of_odf, longitude, latitude, location) VALUES
 ('10000000-0000-0000-0000-000000000001', :'t', 'OLT-IKJ-01', 'Allen Avenue POP, Ikeja', 4, 3.3530, 6.6010, ST_SetSRID(ST_MakePoint(3.3530, 6.6010), 4326)),
 ('10000000-0000-0000-0000-000000000002', :'t', 'OLT-IKJ-02', 'Opebi Road POP',          2, 3.3650, 6.5960, ST_SetSRID(ST_MakePoint(3.3650, 6.5960), 4326));

INSERT INTO cabinets (id, tenant_id, cabinet_id, capacity, number_tray, longitude, latitude, location) VALUES
 ('20000000-0000-0000-0000-000000000001', :'t', 'CAB-ALN-01', 144, 12, 3.3555, 6.6032, ST_SetSRID(ST_MakePoint(3.3555, 6.6032), 4326)),
 ('20000000-0000-0000-0000-000000000002', :'t', 'CAB-TOY-02',  96,  8, 3.3490, 6.5975, ST_SetSRID(ST_MakePoint(3.3490, 6.5975), 4326)),
 ('20000000-0000-0000-0000-000000000003', :'t', 'CAB-OPB-03', 144, 12, 3.3620, 6.5990, ST_SetSRID(ST_MakePoint(3.3620, 6.5990), 4326));

INSERT INTO splitter_boxes (id, tenant_id, box_id, input_ports, output_ports, splitter_level, splitter_type, number_customer,
                            longitude, latitude, location, cabinet_id, parent_splitter_id, is_deleted) VALUES
 ('30000000-0000-0000-0000-000000000001', :'t', 'SPL-ALN-01', 1,  8, 'First-Level',  'PCC',     6, 3.3560, 6.6040, ST_SetSRID(ST_MakePoint(3.3560, 6.6040), 4326), '20000000-0000-0000-0000-000000000001', NULL, false),
 ('30000000-0000-0000-0000-000000000002', :'t', 'SPL-ALN-02', 1, 16, 'Second-Level', 'PCC',    11, 3.3572, 6.6051, ST_SetSRID(ST_MakePoint(3.3572, 6.6051), 4326), '20000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', false),
 ('30000000-0000-0000-0000-000000000003', :'t', 'SPL-TOY-01', 1,  8, 'First-Level',  'PCC',     3, 3.3482, 6.5968, ST_SetSRID(ST_MakePoint(3.3482, 6.5968), 4326), '20000000-0000-0000-0000-000000000002', NULL, false),
 ('30000000-0000-0000-0000-000000000004', :'t', 'SPL-OPB-01', 1,  8, 'First-Level',  'Legacy',  5, 3.3628, 6.6002, ST_SetSRID(ST_MakePoint(3.3628, 6.6002), 4326), '20000000-0000-0000-0000-000000000003', NULL, false),
 ('30000000-0000-0000-0000-000000000005', :'t', 'SPL-OLD-99', 1,  8, 'First-Level',  'PCC',     0, 3.3500, 6.6000, ST_SetSRID(ST_MakePoint(3.3500, 6.6000), 4326), NULL, NULL, true);
