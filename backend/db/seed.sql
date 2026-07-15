-- Sample data mirroring the frontend's src/data/sampleJobs.js
-- Run with: psql -d smarterjobhunt -f db/seed.sql

-- Demo login: demo@smarterjobhunt.dev / demopassword123
INSERT INTO users (email, password_hash) VALUES
    ('demo@smarterjobhunt.dev',
     'scrypt:32768:8:1$7zFd1Z2yvKgq8ce7$2d8da1f36a4697ea9ad39c5781bd54b0cf74936d8d0be7aaf37066538192df4c46a34283063389558a8cbc463de4c7ba947c28e12f337dd13ac4893e7141163c')
ON CONFLICT (email) DO NOTHING;

INSERT INTO companies (name, funding_stage) VALUES
    ('Northlane Robotics', 'series_b'),
    ('Fielded', 'series_a'),
    ('Harborline', 'seed'),
    ('Kestrel Health', 'series_b')
ON CONFLICT DO NOTHING;

-- Headline jobs (one per company, matching the frontend mock)
INSERT INTO jobs (company_id, title, department, location, date_posted) VALUES
    ((SELECT id FROM companies WHERE name = 'Northlane Robotics'),
     'Senior Product Manager', 'Product', 'Remote (US)', '2026-07-10'),
    ((SELECT id FROM companies WHERE name = 'Fielded'),
     'Frontend Engineer, Growth', 'Engineering', 'Bengaluru, IN', '2026-07-12'),
    ((SELECT id FROM companies WHERE name = 'Harborline'),
     'Data Analyst, Marketplace', 'Data', 'Remote (Global)', '2026-07-08'),
    ((SELECT id FROM companies WHERE name = 'Kestrel Health'),
     'Technical Program Manager', 'Operations', 'Mumbai, IN', '2026-07-05');

-- A few extra roles per company so "other jobs at this company" has real counts
INSERT INTO jobs (company_id, title, department, location, date_posted)
SELECT c.id, t.title, t.department, t.location, CURRENT_DATE - (t.days_ago || ' days')::interval
FROM companies c
JOIN LATERAL (
    VALUES
        ('Northlane Robotics', 'Staff Product Manager', 'Product', 'Remote (US)', 3),
        ('Northlane Robotics', 'Product Designer', 'Design', 'Remote (US)', 5),
        ('Northlane Robotics', 'Engineering Manager', 'Engineering', 'Remote (US)', 6),
        ('Northlane Robotics', 'Solutions Engineer', 'Engineering', 'Austin, TX', 9),
        ('Northlane Robotics', 'Recruiter', 'People', 'Remote (US)', 11),
        ('Northlane Robotics', 'Customer Success Manager', 'Support', 'Remote (US)', 14),
        ('Fielded', 'Backend Engineer', 'Engineering', 'Bengaluru, IN', 4),
        ('Fielded', 'QA Engineer', 'Engineering', 'Remote (India)', 7),
        ('Fielded', 'Marketing Manager', 'Marketing', 'Bengaluru, IN', 10),
        ('Harborline', 'Data Engineer', 'Data', 'Remote (Global)', 6),
        ('Harborline', 'Sales Development Rep', 'Sales', 'Remote (Global)', 8),
        ('Kestrel Health', 'Clinical Ops Associate', 'Operations', 'Mumbai, IN', 2),
        ('Kestrel Health', 'Backend Engineer', 'Engineering', 'Mumbai, IN', 4),
        ('Kestrel Health', 'Product Manager', 'Product', 'Remote (India)', 5),
        ('Kestrel Health', 'Compliance Analyst', 'Legal', 'Mumbai, IN', 6),
        ('Kestrel Health', 'Field Nurse Coordinator', 'Operations', 'Pune, IN', 8),
        ('Kestrel Health', 'Data Analyst', 'Data', 'Remote (India)', 9),
        ('Kestrel Health', 'Customer Support Lead', 'Support', 'Mumbai, IN', 12),
        ('Kestrel Health', 'Growth Marketer', 'Marketing', 'Remote (India)', 13),
        ('Kestrel Health', 'Office Manager', 'Operations', 'Mumbai, IN', 15)
) AS t(company_name, title, department, location, days_ago)
    ON t.company_name = c.name;

-- Match scores for the demo user against the four headline jobs
INSERT INTO job_matches (user_id, job_id, match_percent)
SELECT u.id, j.id, m.pct
FROM users u
JOIN LATERAL (
    VALUES
        ('Senior Product Manager', 94),
        ('Frontend Engineer, Growth', 88),
        ('Data Analyst, Marketplace', 76),
        ('Technical Program Manager', 71)
) AS m(title, pct) ON true
JOIN jobs j ON j.title = m.title
WHERE u.email = 'demo@smarterjobhunt.dev'
ON CONFLICT (user_id, job_id) DO NOTHING;

-- Saved searches, matching the frontend mock
INSERT INTO saved_searches (user_id, name, job_title, funding_filter)
SELECT u.id, s.name, s.job_title, 'both'
FROM users u
JOIN LATERAL (
    VALUES
        ('Project Manager 1', 'Project Manager'),
        ('Program Manager 1', 'Program Manager'),
        ('Race Car Driver', 'Race Car Driver')
) AS s(name, job_title) ON true
WHERE u.email = 'demo@smarterjobhunt.dev'
ON CONFLICT (user_id, name) DO NOTHING;
