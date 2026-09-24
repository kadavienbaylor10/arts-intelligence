-- Run in the Supabase SQL Editor AFTER 01_schema.sql and 02_seed_reference.sql.
-- Loads the seed sources (safe to run more than once).

-- 1. Make sure every state referenced by a source has a state row
INSERT INTO places (name, place_kind, state_code)
SELECT v.code, 'state', v.code FROM (VALUES ('AK'), ('AL'), ('AR'), ('AZ'), ('CA'), ('CO'), ('CT'), ('DC'), ('DE'), ('FL'), ('GA'), ('HI'), ('ID'), ('IL'), ('IN'), ('KS'), ('KY'), ('LA'), ('MA'), ('MD'), ('ME'), ('MI'), ('MN'), ('MO'), ('MT'), ('NC'), ('ND'), ('NE'), ('NH'), ('NM'), ('NV'), ('NY'), ('OH'), ('OK'), ('OR'), ('PA'), ('RI'), ('SC'), ('SD'), ('TN'), ('TX'), ('UT'), ('VA'), ('VT'), ('WA'), ('WI'), ('WV'), ('WY')) AS v(code)
WHERE NOT EXISTS (SELECT 1 FROM places p WHERE p.place_kind = 'state' AND p.state_code = v.code);

-- 2. Insert the sources, linking each to its state
INSERT INTO sources (name, url, tier, category, place_id, fetch_method, check_every, tos_notes, discovered_via)
SELECT v.name, v.url, v.tier::source_tier, v.category::source_category, p.id, v.fetch_method::fetch_method,
       make_interval(days => v.days), v.notes, 'seed'
FROM (VALUES
  ('NEA Grants for Arts Projects', 'https://www.arts.gov/grants/grants-for-arts-projects', 'P1_OFFICIAL', 'FEDERAL', NULL, 'HTML', 7, 'New guidelines expected late Dec 2026'),
  ('NEA Challenge America', 'https://www.arts.gov/grants/challenge-america', 'P1_OFFICIAL', 'FEDERAL', NULL, 'HTML', 7, 'Applied for within GAP'),
  ('NEA Our Town', 'https://www.arts.gov/grants/our-town', 'P1_OFFICIAL', 'FEDERAL', NULL, 'HTML', 7, 'Applied for within GAP (Design & Our Town)'),
  ('NEA Research Awards', 'https://www.arts.gov/grants/research-awards', 'P1_OFFICIAL', 'FEDERAL', NULL, 'HTML', 14, NULL),
  ('NEA State and Regional Arts Organizations directory', 'https://www.arts.gov/state-and-regional-arts-organizations', 'P1_OFFICIAL', 'FEDERAL', NULL, 'HTML', 30, 'Several listed agency URLs are outdated'),
  ('NEA Recent Grant Search', 'https://grantsearch.nea.gov/', 'P1_OFFICIAL', 'FEDERAL', NULL, 'MANUAL', 30, 'robots.txt disallows automated access - use manual export only'),
  ('Arts Midwest', 'http://www.artsmidwest.org/', 'P1_OFFICIAL', 'REGIONAL', NULL, 'HTML', 14, 'IA IL IN MI MN ND OH SD WI'),
  ('Creative West (formerly WESTAF)', 'http://creativewest.org/', 'P1_OFFICIAL', 'REGIONAL', NULL, 'HTML', 14, 'AK AZ CA CO HI ID MT NM NV OR UT WA WY'),
  ('Mid-America Arts Alliance', 'http://www.maaa.org/', 'P1_OFFICIAL', 'REGIONAL', NULL, 'HTML', 14, 'AR KS MO NE OK TX'),
  ('Mid Atlantic Arts', 'http://www.midatlanticarts.org/', 'P1_OFFICIAL', 'REGIONAL', NULL, 'HTML', 14, 'DC DE MD NJ NY PA VA WV'),
  ('New England Foundation for the Arts', 'http://www.nefa.org/', 'P1_OFFICIAL', 'REGIONAL', NULL, 'HTML', 14, 'CT MA ME NH RI VT'),
  ('South Arts', 'http://www.southarts.org/', 'P1_OFFICIAL', 'REGIONAL', NULL, 'HTML', 14, 'AL FL GA KY LA MS NC SC TN'),
  ('Alaska State Council on the Arts', 'https://arts.alaska.gov/grants-to-organizations', 'P1_OFFICIAL', 'STATE', 'AK', 'HTML', 14, NULL),
  ('Connecticut Office of the Arts', 'https://portal.ct.gov/DECD/Content/Arts-and-Culture/Funding_Opportunities', 'P1_OFFICIAL', 'STATE', 'CT', 'HTML', 14, NULL),
  ('Delaware Division of the Arts', 'https://arts.delaware.gov/project-support', 'P1_OFFICIAL', 'STATE', 'DE', 'HTML', 14, NULL),
  ('Hawaii State Foundation on Culture and the Arts', 'https://sfca.hawaii.gov/grants-programs/biennium-grants/', 'P1_OFFICIAL', 'STATE', 'HI', 'HTML', 14, NULL),
  ('Maine Arts Commission', 'https://mainearts.maine.gov/Pages/Funding/Grants-Home', 'P1_OFFICIAL', 'STATE', 'ME', 'HTML', 14, NULL),
  ('Maryland State Arts Council', 'https://msac.org/programs/grants-organizations', 'P1_OFFICIAL', 'STATE', 'MD', 'HTML', 14, 'Operating support'),
  ('Montana Arts Council', 'https://art.mt.gov/sigguidelines', 'P1_OFFICIAL', 'STATE', 'MT', 'HTML', 14, NULL),
  ('Nebraska Arts Council', 'https://artscouncil.nebraska.gov/arts-project-grant', 'P1_OFFICIAL', 'STATE', 'NE', 'HTML', 14, NULL),
  ('New Hampshire State Council on the Arts', 'https://www.nharts.dncr.nh.gov', 'P1_OFFICIAL', 'STATE', 'NH', 'HTML', 14, 'Homepage - locate grants page'),
  ('New Mexico Arts', 'https://nmarts.org/grants/', 'P1_OFFICIAL', 'STATE', 'NM', 'HTML', 14, NULL),
  ('North Dakota Council on the Arts', 'https://www.arts.nd.gov/grants', 'P1_OFFICIAL', 'STATE', 'ND', 'HTML', 14, NULL),
  ('Rhode Island State Council on the Arts', 'http://www.arts.ri.gov/', 'P1_OFFICIAL', 'STATE', 'RI', 'HTML', 14, 'Homepage - locate grants page'),
  ('South Dakota Arts Council', 'https://artscouncil.sd.gov/grants/project.aspx', 'P1_OFFICIAL', 'STATE', 'SD', 'HTML', 14, NULL),
  ('Vermont Arts Council', 'https://www.vermontartscouncil.org/grants/find-a-grant/organizations/', 'P1_OFFICIAL', 'STATE', 'VT', 'HTML', 14, NULL),
  ('West Virginia Dept of Arts Culture and History', 'https://wvculture.org/', 'P1_OFFICIAL', 'STATE', 'WV', 'HTML', 14, 'Homepage - locate grants page'),
  ('Wyoming Arts Council', 'https://wyoarts.state.wy.us/wac-grant/arts-access-grant', 'P1_OFFICIAL', 'STATE', 'WY', 'HTML', 14, NULL),
  ('New York State Council on the Arts', 'https://arts.ny.gov/OpportunityGuidelines', 'P1_OFFICIAL', 'STATE', 'NY', 'HTML', 7, NULL),
  ('California Arts Council', 'https://arts.ca.gov/2026_impactprojects_guidelines', 'P1_OFFICIAL', 'STATE', 'CA', 'PDF', 14, NULL),
  ('Illinois Arts Council Agency', 'https://arts.illinois.gov/grants-programs/overview', 'P1_OFFICIAL', 'STATE', 'IL', 'HTML', 14, NULL),
  ('Texas Commission on the Arts', 'https://www.arts.texas.gov/ow/tcagrant/TXArtsPlan/ARP.htm', 'P1_OFFICIAL', 'STATE', 'TX', 'HTML', 14, NULL),
  ('DC Commission on the Arts and Humanities', 'https://dcarts.dc.gov/grants/fy27-projects-events-or-festivals-pef-grant', 'P1_OFFICIAL', 'STATE', 'DC', 'HTML', 14, NULL),
  ('Pennsylvania Council on the Arts', 'https://www.pa.gov/arts', 'P1_OFFICIAL', 'STATE', 'PA', 'HTML', 14, NULL),
  ('Florida Division of Arts and Culture', 'https://dos.fl.gov/cultural/grants/grant-programs/', 'P1_OFFICIAL', 'STATE', 'FL', 'HTML', 14, NULL),
  ('Georgia Council for the Arts', 'https://gaarts.org/what-we-do/grants/', 'P1_OFFICIAL', 'STATE', 'GA', 'HTML', 14, NULL),
  ('Mass Cultural Council', 'https://massculturalcouncil.org/', 'P1_OFFICIAL', 'STATE', 'MA', 'HTML', 14, 'Homepage - locate grants page'),
  ('Arizona Commission on the Arts', 'https://azarts.gov/grants', 'P1_OFFICIAL', 'STATE', 'AZ', 'HTML', 14, NULL),
  ('ArtsWA', 'https://arts.wa.gov/art-project-grant', 'P1_OFFICIAL', 'STATE', 'WA', 'HTML', 14, NULL),
  ('Colorado Creative Industries', 'https://oedit.colorado.gov/colorado-creative-industries', 'P1_OFFICIAL', 'STATE', 'CO', 'HTML', 14, 'Homepage - locate grants page'),
  ('Minnesota State Arts Board', 'https://www.arts.state.mn.us/', 'P1_OFFICIAL', 'STATE', 'MN', 'HTML', 14, 'Homepage - locate grants page'),
  ('Michigan Arts and Culture Council', 'https://www.michiganbusiness.org/industries/macc/macc-grants/', 'P1_OFFICIAL', 'STATE', 'MI', 'HTML', 14, NULL),
  ('North Carolina Arts Council', 'https://www.ncarts.org/resources/grants/grants-organizations', 'P1_OFFICIAL', 'STATE', 'NC', 'HTML', 14, NULL),
  ('Tennessee Arts Commission', 'https://tnartscommission.org/grants', 'P1_OFFICIAL', 'STATE', 'TN', 'HTML', 14, NULL),
  ('Oregon Arts Commission', 'https://www.oregonartscommission.org/', 'P1_OFFICIAL', 'STATE', 'OR', 'HTML', 14, 'Homepage - locate grants page'),
  ('Ohio Arts Council', 'https://oac.ohio.gov/', 'P1_OFFICIAL', 'STATE', 'OH', 'HTML', 14, 'Homepage - locate grants page'),
  ('Indiana Arts Commission', 'https://www.in.gov/arts/programs-and-services/funding/arts-project-support/', 'P1_OFFICIAL', 'STATE', 'IN', 'HTML', 14, NULL),
  ('Missouri Arts Council', 'https://missouriartscouncil.org/wp-content/uploads/2026/01/Missouri-Arts-Council-Grant-Overview.pdf', 'P1_OFFICIAL', 'STATE', 'MO', 'PDF', 30, NULL),
  ('Kansas Creative Arts Industries Commission', 'https://www.kansascommerce.gov/about-us/commissions-partners/creative-arts-industries-commission/', 'P1_OFFICIAL', 'STATE', 'KS', 'HTML', 14, NULL),
  ('Nevada Arts Council', 'https://www.nvartscouncil.org/grants/', 'P1_OFFICIAL', 'STATE', 'NV', 'HTML', 14, NULL),
  ('Louisiana Division of the Arts', 'https://www.crt.louisiana.gov/cultural-development/arts/grants/', 'P1_OFFICIAL', 'STATE', 'LA', 'HTML', 14, 'Louisiana Project Grants via 9 regional arts councils'),
  ('Utah Division of Arts & Museums', 'https://artsandmuseums.utah.gov/?p=20562', 'P1_OFFICIAL', 'STATE', 'UT', 'HTML', 14, 'Project grants reportedly suspended - verify'),
  ('Virginia Commission for the Arts', 'https://vca.virginia.gov/grant', 'P1_OFFICIAL', 'STATE', 'VA', 'HTML', 14, NULL),
  ('Wisconsin Arts Board', 'https://artsboard.wisconsin.gov/pages/Community/GrantPrograms.aspx', 'P1_OFFICIAL', 'STATE', 'WI', 'HTML', 7, NULL),
  ('Oklahoma Arts Council', 'https://oklahoma.gov/arts/grants/grants-for-organizations/community_arts_experience_grants.html', 'P1_OFFICIAL', 'STATE', 'OK', 'HTML', 14, NULL),
  ('Alabama State Council on the Arts', 'https://arts.alabama.gov/', 'P1_OFFICIAL', 'STATE', 'AL', 'HTML', 14, 'Homepage - locate grants page'),
  ('Kentucky Arts Council', 'http://artscouncil.ky.gov/', 'P1_OFFICIAL', 'STATE', 'KY', 'HTML', 14, 'Homepage - locate grants page'),
  ('South Carolina Arts Commission', 'https://www.southcarolinaarts.com', 'P1_OFFICIAL', 'STATE', 'SC', 'HTML', 14, 'Homepage - locate grants page'),
  ('Arkansas Arts Council', 'https://www.arkansasheritage.com/funding/art-grants', 'P1_OFFICIAL', 'STATE', 'AR', 'HTML', 14, NULL),
  ('Idaho Commission on the Arts', 'http://www.arts.idaho.gov/', 'P1_OFFICIAL', 'STATE', 'ID', 'HTML', 14, 'Homepage - locate grants page')
) AS v(name, url, tier, category, state_code, fetch_method, days, notes)
LEFT JOIN places p ON p.place_kind = 'state' AND p.state_code = v.state_code
ON CONFLICT (url) DO NOTHING;

-- 3. Check: should return 60
SELECT count(*) AS sources_loaded FROM sources;
