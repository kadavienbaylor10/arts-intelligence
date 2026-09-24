-- Run after 01_schema.sql, then import seed_sources.csv into the sources table.

-- Focus states for the MVP (is_target = TRUE)
INSERT INTO places (name, place_kind, state_code, is_target) VALUES
  ('Texas','state','TX',TRUE), ('California','state','CA',TRUE), ('New York','state','NY',TRUE),
  ('Illinois','state','IL',TRUE), ('Florida','state','FL',TRUE), ('Georgia','state','GA',TRUE),
  ('North Carolina','state','NC',TRUE), ('Tennessee','state','TN',TRUE), ('Colorado','state','CO',TRUE),
  ('Washington','state','WA',TRUE), ('Pennsylvania','state','PA',TRUE), ('Massachusetts','state','MA',TRUE),
  ('Louisiana','state','LA',TRUE), ('Arizona','state','AZ',TRUE), ('Minnesota','state','MN',TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO opportunity_types (code, label) VALUES
  ('grant','Grant'), ('rfq','Request for Qualifications'), ('rfp','Request for Proposals'),
  ('rfa','Request for Applications'), ('commission','Commission'), ('residency','Residency'),
  ('fellowship','Fellowship'), ('competition','Competition'), ('research_call','Research call'),
  ('capital_project_signal','Capital project signal (no call yet)'), ('other','Other')
ON CONFLICT DO NOTHING;

INSERT INTO mediums (code, label) VALUES
  ('sculpture','Sculpture'), ('mural','Mural'), ('environmental_graphics','Environmental graphics'),
  ('projection','Projection'), ('light','Light-based'), ('digital','Digital'), ('installation','Installation'),
  ('interactive','Interactive'), ('sound','Sound'), ('community_engaged','Community-engaged'),
  ('design','Design / architecture collaboration'), ('programming','Cultural programming'),
  ('education','Arts education / youth'), ('research','Research'), ('any','Any discipline')
ON CONFLICT DO NOTHING;

-- Link sources to their state place rows after importing the CSV:
-- (the CSV has a state_code column; import it into a temp column or run this with the CSV loaded into a staging table)
-- UPDATE sources s SET place_id = p.id FROM places p, staging_sources st
--  WHERE st.url = s.url AND p.state_code = st.state_code AND p.place_kind = 'state';
