"""
database/import_county_data.py — Seeds the county catalog tables.

Data sources baked in:
  * Entry-level Minimum Qualifications spreadsheet (county HR, dated 8.13.25)
  * Career-ladder progression diagrams from the county CTE Pathways PDF

Run AFTER init_db.py and import_data.py:
    python database/import_county_data.py

Idempotent: re-running upserts programs, positions, and ladders so newer copies
of this script overwrite previous seeds. Existing school/pathway data is left
intact; the script also back-fills pathways.cte_program_id from the pathway's
sector field so a student picking a pathway is taken to its county program.
"""

import os
import sqlite3
import sys
from urllib.parse import quote_plus

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from config.settings import Config

GOVJOBS_BASE = "https://www.governmentjobs.com/careers/sbcounty"

# ---------------------------------------------------------------------------
# 10 CTE Programs (top-level grouping the county uses)
# ---------------------------------------------------------------------------

PROGRAMS = [
    ("Automotive",
     "Vehicle service, maintenance, and repair careers across the County's fleet, "
     "Sheriff motor pool, and Fire agency.", 1),
    ("Arts, Media & Entertainment",
     "Graphics, media production, and visual communication roles in development.", 2),
    ("Business",
     "Office, fiscal, records, applications, and revenue recovery support roles "
     "across County departments. Includes Cyber.", 3),
    ("Patient Care",
     "Front-office and clinical-support roles at County hospitals and clinics. "
     "Includes dental, sports medicine, and bio-medical equipment.", 4),
    ("Building & Construction",
     "Land use, code enforcement, general maintenance, and construction equipment "
     "operator careers.", 5),
    ("Education, Child Development & Family Services",
     "Eligibility, employment services, social work, mental health, and child "
     "support careers serving County residents.", 6),
    ("Energy, Environment & Utilities",
     "Environmental health and inspection careers in Public Health.", 7),
    ("Hospitality, Tourism & Recreation",
     "Custodial, linen, and food service roles supporting County operations.", 8),
    ("Information & Communication Technologies",
     "IT support, GIS, and automated-systems careers across County IT. Includes GIS.", 9),
    ("Public Service",
     "Animal services, animal control, and Sheriff's communications/dispatcher "
     "careers.", 10),
]

# ---------------------------------------------------------------------------
# Sector → Program lookup
#
# The pathways table holds the fine-grained school-side CTE pathway name and a
# sector string from the CDE Industry Sectors. Map those sectors up to the
# county's 10 program groupings so a student picking a pathway is taken to the
# county positions the county has tied to that group.
# Unmapped sectors (Agriculture, Engineering, Manufacturing, Fashion) currently
# have no county-positions; pathways in those sectors will show an empty list.
# ---------------------------------------------------------------------------

SECTOR_TO_PROGRAM = {
    # Arts, Media & Entertainment — various spellings seen in the city spreadsheet
    "Arts, Media, and Entertainment":                 "Arts, Media & Entertainment",
    "Arts, Media, & Entertainment":                   "Arts, Media & Entertainment",
    "Arts Media and Entertainment":                   "Arts, Media & Entertainment",

    # Building & Construction
    "Building and Construction Trades":               "Building & Construction",
    "Building and Construction":                      "Building & Construction",
    "Installation, Maintenance and Repair":           "Building & Construction",

    # Business — wide net so legal, public admin, marketing all roll up here since
    # the county has no separate program for those.
    "Business and Finance":                           "Business",
    "Business":                                       "Business",
    "Marketing, Sales, and Services":                 "Business",
    "Marketing, Sales and Services":                  "Business",
    "Marketing, Sales and Service":                   "Business",
    "Legal Services":                                 "Business",
    "Public Administration":                          "Business",

    # Education / Child Dev / Family Services — multiple short forms
    "Education, Child Development, and Family Services": "Education, Child Development & Family Services",
    "Education Child Development and Family Services":   "Education, Child Development & Family Services",
    "Education":                                         "Education, Child Development & Family Services",
    "Family and Social Services":                        "Education, Child Development & Family Services",

    # Energy, Environment & Utilities
    "Energy, Environment, and Utilities":             "Energy, Environment & Utilities",
    "Energy Environment and Utilities":               "Energy, Environment & Utilities",

    # Patient Care
    "Health Science and Medical Technology":          "Patient Care",
    "Patient Care":                                   "Patient Care",

    # Hospitality, Tourism & Recreation
    "Hospitality, Tourism, and Recreation":           "Hospitality, Tourism & Recreation",
    "Hospitality, Tourism, & Recreation":             "Hospitality, Tourism & Recreation",
    "Hospitality, Tourism and Recreation":            "Hospitality, Tourism & Recreation",

    # ICT
    "Information and Communication Technologies":     "Information & Communication Technologies",
    "Information Communication Technologies":         "Information & Communication Technologies",

    # Public Service — animal services, law enforcement, military all roll up
    "Public Services":                                "Public Service",
    "Public Service":                                 "Public Service",
    "Animal Care Services":                           "Public Service",
    "Law Enforcement and Emergency Response":         "Public Service",
    "Military Service":                               "Public Service",

    # Automotive / Transportation
    "Transportation":                                 "Automotive",
    "Automotive":                                     "Automotive",

    # Intentionally unmapped (no county program covers these):
    #   Agriculture and Natural Resources
    #   Engineering & Architecture / Engineering and Architecture
    #   Fashion and Interior Design
    #   Manufacturing and Product Development
}

# ---------------------------------------------------------------------------
# County positions catalog
#
# Each tuple:
#   (program_name, job_code, title, union_code, grade, min_hr, max_hr, mqs, notes)
# job_code "NEW" means the classification is still in development; mqs may be None.
# ---------------------------------------------------------------------------

POSITIONS = [

    # ===== Automotive =====
    ("Automotive", "05225", "Fleet Services Specialist", "CLT", "31", 18.48, 25.41,
     "One (1) year full-time equivalent of paid work experience servicing, "
     "maintaining or repairing gasoline/diesel powered vehicles, construction "
     "equipment, fuel dispensers, fuel delivery systems, or fuel storage tanks.",
     None),

    ("Automotive", "13080", "Mechanics Assistant", "CLT", "34", 19.86, 27.36,
     "OPTION 1\n"
     "EXPERIENCE: Eighteen (18) months of paid work experience (full-time "
     "equivalent) repairing diesel or gasoline-powered automotive equipment. "
     "Experience must include removal, repair and replacement of radiators, "
     "hoses, belts, water pumps, batteries, cables, alternators, starters, "
     "brake systems, wheel bearings, seals and body parts, etc.\n\n"
     "OPTION 2\n"
     "EXPERIENCE: Six (6) months of hands-on paid work experience (full-time "
     "equivalent) repairing diesel or gasoline-powered automotive equipment. "
     "Experience must include removal, repair and replacement of radiators, "
     "hoses, belts, water pumps, batteries, cables, alternators, starters, "
     "brake systems, wheel bearings, seals and body parts, etc.\n"
     "CERTIFICATE: Possession of an Automotive Technology Certificate, issued "
     "by a school accredited with the US Department of Education, for a "
     "comprehensive course in automotive technology lasting approximately one "
     "(1) year. A legible copy of certification MUST be submitted with the "
     "Application.",
     None),

    ("Automotive", "13265", "Motor Pool Services Assistant", "CLT", "34", 19.86, 27.36,
     "Experience: Six (6) months of full-time equivalent paid work experience "
     "making minor repairs on automotive equipment. (Minor repairs generally "
     "include replacement and maintenance of batteries, cables, tires, fluid "
     "levels, etc.)",
     None),

    ("Automotive", "49109", "Fire Agency Mechanic I", "GSU", "AV8", 24.40, 35.31,
     "Completion of California Fire Mechanics Academy.\n"
     "--OR--\n"
     "Completion of heavy gas and diesel repair/maintenance program.\n"
     "--OR--\n"
     "Eighteen (18) months of heavy-duty repair/maintenance experience.",
     None),

    # ===== Arts, Media & Entertainment (both NEW) =====
    ("Arts, Media & Entertainment", "NEW", "Graphics Assistant", None, None, None, None,
     "Classification in development. Minimum qualifications not yet published.",
     "NEW classification"),

    ("Arts, Media & Entertainment", "NEW", "Media Assistant", None, None, None, None,
     "Classification in development. Minimum qualifications not yet published.",
     "NEW classification"),

    # ===== Business =====
    ("Business", "06050", "Fiscal Assistant", "CLK", "31A", 18.74, 25.74,
     "OPTION 1\n"
     "Experience: Twelve (12) months of full-time work experience performing "
     "fiscal activities where the primary duty involved performance of "
     "arithmetic calculations.\n"
     "Education Substitution: Six (6) semester (9 quarter) units of completed "
     "college level accounting coursework, obtained from an accredited "
     "college/university, may be substituted for up to six (6) months of the "
     "required experience.\n"
     "NOTE: Internship/student experience is not considered qualifying work "
     "experience.\n\n"
     "OPTION 2\n"
     "Education: A completed Associate degree in mathematics, "
     "accounting/finance, or other relevant field of study obtained from an "
     "accredited college/university. A copy of your degree/proof of graduation "
     "must be attached.",
     "Marked for MQ modification"),

    ("Business", "03316", "Office Assistant", "CLK", "6M", 18.07, 24.24,
     "No experience required.",
     None),

    ("Business", "18056", "Records Technician Trainee", "TI", "7MT", 18.40, 24.03,
     "Must possess six (6) months of clerical experience in an office "
     "environment with knowledge of modern office practices including filing, "
     "data entry, operating standard office equipment, basic arithmetic, proper "
     "office etiquette, and reception/customer service techniques in person, on "
     "the telephone and in writing.",
     None),

    ("Business", "20035", "Title Transfer Technician Trainee", "TI", "7MT", 18.40, 24.03,
     "OPTION 1: One (1) year of full-time equivalent work experience in a title "
     "company or comparable organization processing legal property documents "
     "that are used to transfer interest in real property.\n"
     "OPTION 2: Six (6) months of full-time equivalent work experience in a "
     "California Assessor or Recorder office assisting the public and/or "
     "appraisal staff with property information.\n"
     "OPTION 3: Fifteen (15) semester (23 quarter) units of completed college "
     "coursework in business/public administration or other related field.",
     None),

    ("Business", "03358", "Revenue Recovery Officer Trainee", "TI", "36T", 20.92, 28.02,
     "OPTION 1: One (1) year of full-time accounts receivable experience "
     "collecting on delinquent accounts which includes phone calls and/or "
     "personal contact with responsible party.\n"
     "OPTION 2: One (1) year of full-time experience in a collections or fiscal "
     "environment, with primary duties that include setting up accounts, "
     "ensuring or confirming posting of payments to accounts, fielding related "
     "phone calls, collecting preliminary debtor information, and accessing "
     "debtor account information.\n"
     "OPTION 3: One (1) year of full-time experience in medical billing "
     "processing and monitoring medical claims.",
     None),

    ("Business", "01685", "Applications Specialist Trainee", "ADM", "42T", 24.20, 32.44,
     "OPTION 1: Six (6) months of full-time equivalent experience supporting "
     "business applications or healthcare applications (i.e., troubleshoot; "
     "assist and instruct end-users in effective use; resolve problems).\n"
     "Experience must include the use of advanced MS Office Suite features, "
     "such as: creating macros in Word, Excel, or Access; using complex "
     "formulas and PivotTables in Excel; and creating formal PowerPoint "
     "presentations for business use.\n\n"
     "OPTION 2: Experience performing related duties to an Applications "
     "Specialist Trainee as a PSE/WEX/Intern for San Bernardino County AND an "
     "Associate's Degree or higher in computer science, information technology, "
     "data processing, or computer systems analysis (or equivalent coursework). "
     "Candidate must be a current PSE/WEX/Intern, or recently separated within "
     "the last six months.",
     None),

    ("Business", "NEW", "Appraiser Assistant", None, None, None, None,
     "Classification in development. Minimum qualifications not yet published.",
     "NEW classification"),

    # ===== Patient Care =====
    ("Patient Care", "08038", "Health Services Assistant", "TI", "30", 18.40, 24.79,
     "Education: Must possess a high school diploma or GED, or a U.S. Department "
     "of Education approved High School Equivalency Test.\n"
     "--AND--\n"
     "Applicants must also qualify under one of the following:\n"
     "Option A: One (1) year of full-time equivalent experience directly "
     "assisting professionals in providing health or social services. Experience "
     "must include working in a medical front and back office and performing "
     "intake interviews to determine eligibility for medical or social services.\n"
     "Option B: Successful completion of a Medical Assistant (MA) program "
     "(front and back office) or Certified Nursing Assistant (CNA) program "
     "resulting in a certificate.\n"
     "Option C: Successful Completion of the Entry-Level Workplace Certificate "
     "from the SBC Career Path Builder Program.",
     "Marked for MQ modification"),

    ("Patient Care", "16155", "Rehabilitation Services Aide", "TI", "6M", 18.07, 24.24,
     "Option 1: Six (6) months of experience assisting rehabilitation staff "
     "with patient care duties.",
     None),

    ("Patient Care", "03365", "Office Assistant - Healthcare", "CLK", "6M", 18.07, 24.24,
     "Six (6) months of full-time equivalent in-office clerical experience.",
     None),

    ("Patient Care", "08033", "Health Information Management Assistant I", "CLK", "6M", 18.07, 24.24,
     "Experience: Six (6) months, within the last five (5) years, of full-time "
     "equivalent experience primarily performing any of the following:\n"
     " - Auditing and processing electronic medical records in an acute care "
     "hospital or clinical setting\n"
     " - Medical clerical experience, such as processing disability requests, "
     "birth and death certificate documents, and/or release of information "
     "processing\n"
     " - Front office or secretarial experience in a primary or specialty clinic "
     "or private physician's office\n"
     " - Indexing, prepping, scanning documents into the electronic health "
     "record (EHR) system",
     "Marked for MQ modification"),

    ("Patient Care", "02092", "Burn Care Technician", "TI", "30C", 18.46, 25.23,
     "EXPERIENCE: Six (6) months of recent (within the past five (5) years) "
     "full-time equivalent experience assisting professional medical staff in "
     "the care and treatment of burn patients in a burn unit.",
     "Marked for MQ modification"),

    ("Patient Care", "02014", "Bio-Medical Equipment Technician Trainee", "TI", "37T", 21.40, 28.74,
     "No MQs for Trainee level. 24 months to promote to journey.\n"
     "MQ for Journey Experience: Two (2) years of experience repairing and "
     "maintaining a variety of medical and laboratory electronic and electrical "
     "equipment.",
     None),

    # ===== Building & Construction =====
    ("Building & Construction", "12050", "Land Use Technician Trainee", "TI", "30T", 18.40, 24.19,
     "Candidates must meet one of the options below to qualify.\n"
     "OPTION 1: Six (6) months of experience working in San Bernardino County "
     "Land Use Services.\n"
     "OPTION 2: One (1) year of experience assisting the public with "
     "interpreting building codes and ordinances, processing permit "
     "applications, explaining rules and regulations of a public agency; "
     "customer service experience that included fielding and investigating "
     "complaints.\n"
     "OPTION 3: Fifteen (15) semester (23 quarter) units of completed college "
     "coursework in urban development, building inspection technology, code "
     "enforcement, land surveying or a closely related field.",
     None),

    ("Building & Construction", "07030", "General Maintenance Mechanic", "CLT", "43", 24.79, 34.11,
     "REQUIRED EXPERIENCE: Four (4) years of journey-level experience "
     "performing maintenance and repair of large commercial or industrial "
     "buildings in at least one (1) of the following trades: landscaping "
     "and/or irrigation, electrical, plumbing, heating/ventilation/air "
     "conditioning (HVAC), or carpentry.\n"
     "Note: Residential building experience and new construction experience are "
     "NOT considered qualifying.\n"
     "-OR-\n"
     "COMPLETION OF APPRENTICESHIP: Successful completion of a structured, "
     "formal four (4) year trade apprenticeship program resulting in "
     "journey-level status in one (1) of the trades listed above.",
     None),

    ("Building & Construction", "07025", "General Maintenance Worker", "CLT", "36C", 21.30, 29.24,
     "REQUIRED EXPERIENCE: Two (2) years of full-time skilled or semi-skilled "
     "experience performing maintenance and repair of commercial or industrial "
     "buildings in at least one (1) of the following trades: electrical, "
     "plumbing, heating/ventilation/air conditioning (HVAC), and carpentry.\n"
     "Note: Residential building experience and new construction experience are "
     "not considered qualifying.\n"
     "-OR-\n"
     "REQUIRED APPRENTICESHIP COMPLETION: Successful completion of a "
     "structured, formal four (4) year trade apprenticeship program resulting "
     "in journey-level status in one (1) of the trades listed above.\n"
     "Note: A copy of your certificate MUST be attached with the application.",
     None),

    ("Building & Construction", "05186", "Construction Equipment Worker Trainee", "CLT", "36T", 20.92, 28.02,
     "License: Must have a valid Class C Driver License.\n"
     "--AND--\n"
     "Experience: Three (3) months of experience working in construction, "
     "maintenance, fabrication, mechanical, industrial, performing general "
     "labor OR closely related field work.",
     None),

    ("Building & Construction", "05191", "Equipment Operator", "CLT", "42C", 24.63, 33.84,
     "LICENSE: A valid Class A or B Driver's License that has a tanker "
     "endorsement AND no restrictions for manual transmission and air brakes "
     "is required.\n"
     "--AND--\n"
     "EXPERIENCE\n"
     "Option 1: Nine (9) months of experience working as a Construction "
     "Equipment Worker for the County of San Bernardino. (Construction "
     "Equipment Worker Trainee experience is not considered qualifying for "
     "this option.)\n"
     "Option 2: Two (2) years of experience in the maintenance/construction of "
     "roadways, flood control facilities, airports, landfills, or similar "
     "public works settings operating medium and/or heavy equipment. (Building "
     "construction experience is not considered qualifying.)",
     None),

    ("Building & Construction", "10020", "Code Enforcement Officer I", "TI", "42T", 24.20, 32.44,
     "Candidates must meet one of the following options:\n"
     "Option 1: Twelve (12) months (full-time equivalent) experience "
     "interpreting, explaining, and enforcing rules and regulations for a "
     "public agency.\n"
     "Option 2: Twelve (12) months (full-time equivalent) experience "
     "interpreting and explaining code enforcement, planning, or land use "
     "rules and regulations.\n"
     "Option 3: Twenty (20) semester (30 quarter) units of completed college "
     "coursework in inspection/construction technology, planning, land use, "
     "fire technology, police science, criminal justice or a related field; "
     "-- OR -- possession of an Associate's Degree (or higher).\n"
     "Option 4: Six (6) months (full-time equivalent) experience working "
     "within San Bernardino County Land Use Services, Code Enforcement "
     "Division performing a variety of duties in support of code enforcement "
     "activities.",
     None),

    # ===== Education, Child Development & Family Services =====
    ("Education, Child Development & Family Services", "05110", "Eligibility Worker I", "TI", "31T", 18.48, 24.81,
     "Applicants must meet one of the following options:\n"
     "Option 1: Two (2) years of full-time experience interviewing and "
     "gathering financial, family, or personal information from the public over "
     "the phone or in-person. Experience must include computer usage.\n"
     "Option 2: One (1) year of the above experience PLUS fifteen (15) "
     "semester (23 quarter) units of completed college coursework in "
     "behavioral/social science or public/business administration.\n"
     "Option 3: Thirty (30) semester (45 quarter) units of completed college "
     "coursework in behavioral/social science or business/public administration.\n"
     "Option 4: Completion of an Associate's degree or higher in any field.\n"
     "Option 5: Completion of the 'Case Management in the Public Sector "
     "Certificate' from San Bernardino Valley College or Certificate of "
     "Completion from the SBC Career PathBuilder Program.\n"
     "Option 6: Six (6) months of full-time experience working as a Public "
     "Service Employee (PSE) with the San Bernardino County Transitional "
     "Assistance Department (TAD).",
     None),

    ("Education, Child Development & Family Services", "05119", "Employment Special Services Trainee", "ADM", "36T", 20.92, 28.02,
     "Experience: One (1) year of full-time work experience interpreting, "
     "applying, and explaining (organizational or government) policies, "
     "regulations, or procedures to the public.\n"
     "--AND--\n"
     "Education: Thirty (30) semester (45 quarter) units of completed college "
     "coursework in behavioral/social science, business/public administration, "
     "education, or closely related field.",
     None),

    ("Education, Child Development & Family Services", "06011", "Peer and Family Advocate", "ADM", "32", 18.94, 26.05,
     "Education: High School Diploma or general equivalency degree (GED)\n"
     "--AND--\n"
     "Experience: Two (2) years of full-time equivalent experience (4,160 "
     "hours of paid or volunteer experience) in mental health, substance use, "
     "social, or human services.",
     None),

    ("Education, Child Development & Family Services", "19608", "Social Worker I", "ADM", "41", 23.59, 32.45,
     "Education: A Master's degree in Social Work (MSW) from a school "
     "accredited by the Council of Social Work Education as required by "
     "Title 22 state regulations.\n"
     "--AND--\n"
     "Experience: 500 hours of supervised clinical internship.",
     "Marked for MQ modification"),

    ("Education, Child Development & Family Services", "13222", "Mental Health Specialist Trainee", "ADM", "34T", 19.86, 26.68,
     "Must meet one (1) of the following options:\n"
     "Option 1: Thirty (30) semester (45 quarter) units of completed "
     "coursework from an accredited college in behavioral or social science.\n"
     "Option 2: Sixty (60) semester (90 quarter units) of completed coursework "
     "from an accredited college, which includes 15 semester (23 quarter) "
     "units in behavioral or social science.",
     None),

    ("Education, Child Development & Family Services", "19790", "Child Support Assistant", "TI", "33A", 19.67, 27.02,
     "Applicants must meet one of the following options:\n"
     "OPTION 1 EDUCATION: Thirty (30) semester or forty-five (45) quarter "
     "units of completed college coursework from an accredited college or "
     "university in Public/Business Administration, Administration of Justice, "
     "Social/Behavioral Science, English, Math, Humanities, or a closely "
     "related field.\n"
     "OPTION 2 EXPERIENCE: One (1) year of full-time equivalent office "
     "clerical experience working in a county agency overseen by a State "
     "Child Support Services Department.\n"
     "OPTION 3 EXPERIENCE: One (1) year of full-time equivalent office "
     "clerical experience which involved interviewing customers to obtain "
     "pertinent financial, legal, or personal history information.\n"
     "OPTION 4 CERTIFICATION: Successful completion of the Entry Level "
     "Workplace Certification issued by San Bernardino County.",
     None),

    ("Education, Child Development & Family Services", "19563", "Social Services Aide", "TI", "32", 18.94, 26.05,
     "Option 1: Twenty-four (24) semester (36 quarter) units of completed "
     "college coursework in behavioral/social science or humanities.\n"
     "Option 2: Twelve (12) months of experience in a human/social services "
     "program, which included interviewing clients to assess human services "
     "needs, assisting individuals in obtaining tangible services, and "
     "explaining rules, policies, and program services to clients.\n"
     "Option 3: Eighteen (18) months of office clerical experience which "
     "involved substantial client contact in a human/social services program.",
     None),

    # ===== Energy, Environment & Utilities =====
    ("Energy, Environment & Utilities", "05154", "Environmental Technician I", "TI", "36", 20.92, 28.73,
     "Six (6) months of full-time equivalent experience explaining program "
     "related regulations and requirements to the public in an Environmental "
     "Health, Code Enforcement, other DPH program/division/section, or other "
     "public sector agency program/department setting, with experience in any "
     "of the following:\n"
     " - Processing applications for permits, licenses, certifications, and/or "
     "other closely related government regulated documents and/or records.\n"
     " - Performing surveillance and inspection duties in Environmental Health "
     "programs.\n"
     " - Assisting with food facilities, recreation (public swimming pools), "
     "insect and rodent vector control, or land use inspections.",
     None),

    # ===== Hospitality, Tourism & Recreation =====
    ("Hospitality, Tourism & Recreation", "12178", "Linen Room Attendant", "CLT", "6M", 18.07, 24.24,
     "No experience required.",
     None),

    ("Hospitality, Tourism & Recreation", "06111", "Food Service Worker", "CLT", "7M", 18.40, 24.64,
     "Three (3) months of full-time food service experience in a restaurant, "
     "fast food establishment, cafeteria, hotel, banquet room, hospital, "
     "correctional facility kitchen, school, military, senior living facility "
     "or similar environment.\n"
     "--AND--\n"
     "Certificate: Incumbents must obtain a San Bernardino County Food "
     "Handler's Certificate within two (2) weeks of hire.",
     "Marked for MQ modification"),

    # ===== Information & Communication Technologies =====
    ("Information & Communication Technologies", "03431", "GIS Technician Trainee", "TI", "39T", 22.48, 30.17,
     "Applicants must meet one of the qualifying options listed below:\n"
     "OPTION 1: Nine (9) semester or fourteen (14) quarter units of completed "
     "college coursework in GIS software and theory, geographic information "
     "systems, GIScience, geography, cartography, drafting, surveying, or "
     "information technology or a closely related field.\n"
     "OPTION 2: Six (6) months of experience using GIS software to update "
     "geospatial databases.\n"
     "OPTION 3: Six (6) months of experience serving as a PSE, WEX, or Intern "
     "for a San Bernardino County department, performing GIS related duties.",
     None),

    ("Information & Communication Technologies", "15019", "IT Technical Assistant Trainee", "TI", "30T", 18.40, 24.19,
     "Applicant must meet one of the following options:\n"
     "Option 1 - Education: Thirty (30) semester (45 quarter) units in Office "
     "Automation/Administration, Data Entry, Information Systems/Technology or "
     "a closely related field from an accredited university/college or "
     "technical school.\n"
     "Option 2 - Experience: One (1) year of work experience which included "
     "frequent use of advanced features of Microsoft Office Suite, i.e., Word, "
     "Excel, Power Point and Outlook.",
     None),

    ("Information & Communication Technologies", "01679", "Automated Systems Technician", "TI", "44", 25.38, 34.90,
     "Eligible candidates must meet ONE of the below qualifying options.\n\n"
     "OPTION 1\n"
     "EXPERIENCE: Six (6) months of full-time equivalent experience in a "
     "customer service environment providing IT technical support for "
     "computerized systems.\n"
     "EDUCATION: Fifteen (15) semester or twenty-three (23) quarter units of "
     "completed post-high school level coursework from an accredited college "
     "and university in information technology, computer sciences, or closely "
     "related field. OR CompTIA: A+, Network +, Security +, MCSE, CCNA or "
     "comparable certificate.\n\n"
     "OPTION 2\n"
     "EXPERIENCE: Current San Bernardino County PSE/WEX/Intern performing "
     "related duties to an Automated Systems Technician with an Associate's "
     "Degree in information technology, computer sciences, or closely related "
     "field (or equivalent).\n\n"
     "SUBSTITUTION OPTIONS\n"
     "EXPERIENCE: Six (6) months of additional qualifying experience may "
     "substitute for the required education or certification.\n"
     "EDUCATION: A completed Bachelor's Degree from an accredited college and "
     "university in information technology, computer sciences, or closely "
     "related field may substitute for the required six (6) months of "
     "qualifying experience.",
     None),

    # ===== Public Service =====
    ("Public Service", "43008", "Animal Keeper I", "NRP", "N14", 18.66, 27.09,
     "One (1) year full time equivalent (40 hours per week) experience "
     "providing animal care, feeding, training, exercising, "
     "observing/documenting behavior, and cleaning enclosures, in a zoo, "
     "hospital/clinic, wildlife rehabilitation center or similar experience. "
     "Experience must include a variety of wildlife/exotic animals or "
     "sick/injured animals.\n"
     "Volunteer, internship, or professional experience is acceptable and must "
     "be included in the work experience section of your application.",
     None),

    ("Public Service", "01227", "Animal License Checker I", "TI", "6M", 18.07, 24.24,
     "Driver License: Applicants must possess and maintain a current, valid "
     "California Class C driver license and a clean driving record.\n"
     "Note: Applicants must indicate California driver license number and "
     "expiration date on the application, or your application will be "
     "disqualified.",
     None),

    ("Public Service", "01226", "Animal Control Officer", "TI", "41A", 23.90, 32.87,
     "Applicants must meet one (1) of the following options:\n"
     "Option A: Six (6) months of full-time equivalent experience "
     "interpreting, explaining, and enforcing rules and regulations for a "
     "public agency.\n"
     "Option B: Six (6) months of full-time equivalent experience in animal "
     "handling/care working in a veterinary clinic, animal shelter, or kennel "
     "operation.\n"
     "Option C: Possession of a Registered Veterinary Technician Certificate "
     "issued by the State of California.",
     None),

    ("Public Service", "19478", "Sheriff's Communications Dispatcher Trainee", "TI", "42T", 24.20, 32.44,
     "Keyboarding: 40 words per minute\n"
     "Experience: No experience required.\n\n"
     "**Candidates must be 18 years of age at time of application**",
     None),
]

# ---------------------------------------------------------------------------
# Career-ladder progression chains (transcribed from CTE Pathways PDF)
#
# Each entry: entry_title → ordered list of subsequent step titles.
# Step 1 (the entry position itself) is implicit and not stored here.
# ---------------------------------------------------------------------------

LADDERS = {
    # Automotive
    "Fleet Services Specialist":            ["Fleet Technician I", "Fleet Technician II", "Lead Fleet Technician", "Fleet Supervisor"],
    "Mechanics Assistant":                  ["Fleet Technician I", "Fleet Technician II", "Lead Fleet Technician", "Fleet Supervisor"],
    "Motor Pool Services Assistant":        ["Sheriff's Maintenance Mechanic Trainee", "Sheriff's Maintenance Mechanic", "Sheriff's Maintenance Manager"],
    "Fire Agency Mechanic I":               ["Fire Agency Mechanic II", "Lead Fire Mechanic", "Vehicle Services Supervisor"],

    # Business
    "Fiscal Assistant":                     ["Fiscal Specialist", "Lead Office Specialist", "Supervising Fiscal Specialist"],
    "Office Assistant":                     ["Senior Office Assistant", "Lead Office Assistant", "Supervising Office Assistant"],
    "Applications Specialist Trainee":      ["Applications Specialist"],
    "Records Technician Trainee":           ["Records Technician", "Senior Records Technician", "Records Technician Supervisor I", "Records Technician Supervisor II"],
    "Title Transfer Technician Trainee":    ["Title Transfer Technician I", "Title Transfer Technician II", "Supervising Title Transfer Technician I", "Supervising Title Transfer Technician II"],
    "Revenue Recovery Officer Trainee":     ["Revenue Recovery Officer I", "Revenue Recovery Officer II", "Supervising Revenue Recovery Officer", "Revenue Recovery Manager"],

    # Patient Care
    "Office Assistant - Healthcare":        ["Senior Office Assistant - Healthcare", "Lead Office Assistant", "Supervising Office Assistant"],
    "Bio-Medical Equipment Technician Trainee": ["Bio-Medical Equipment Technician I", "Bio-Medical Equipment Technician II"],

    # Building & Construction
    "Land Use Technician Trainee":          ["Land Use Technician", "Senior Land Use Technician", "Land Use Technician Supervisor"],
    "General Maintenance Mechanic":         ["Maintenance Supervisor"],
    "General Maintenance Worker":           ["Maintenance Supervisor"],
    "Construction Equipment Worker Trainee":["Construction Equipment Worker", "Maintenance and Construction Supervisor I/II"],
    "Equipment Operator":                   ["Senior Equipment Operator", "Maintenance and Construction Supervisor I/II"],
    "Code Enforcement Officer I":           ["Code Enforcement Officer II", "Code Enforcement Officer III", "Code Enforcement Supervisor"],

    # Education, Child Development & Family Services
    "Eligibility Worker I":                 ["Eligibility Worker II", "Eligibility Worker III", "Eligibility Worker Supervisor"],
    "Employment Special Services Trainee":  ["Employment Services Specialist", "Supervising Employment Services Specialist"],
    "Peer and Family Advocate":             ["Mental Health Specialist / Social Worker", "Clinic Supervisor / Supervising Social Worker"],
    "Social Worker I":                      ["Social Worker II", "Supervising Social Worker"],
    "Mental Health Specialist Trainee":     ["Mental Health Specialist", "Clinic Supervisor"],
    "Child Support Assistant":              ["Child Support Specialist", "Senior Child Support Specialist", "Supervising Child Support Specialist"],
    "Social Services Aide":                 ["Administrative Social Worker", "Supervising Social Worker"],

    # Energy, Environment & Utilities
    "Environmental Technician I":           ["Environmental Technician II", "Supervising Environmental Health Specialist"],

    # Hospitality, Tourism & Recreation
    "Linen Room Attendant":                 ["Custodian", "Lead Custodian", "Supervising Custodian"],
    "Food Service Worker":                  ["Food Services Supervisor"],

    # ICT
    "GIS Technician Trainee":               ["GIS Technician I", "GIS Technician II", "GIS Technician III", "Supervising GIS Technician"],
    "IT Technical Assistant Trainee":       ["IT Technical Assistant I", "IT Technical Assistant II", "Supervising Automated Systems Analyst I/II"],
    "Automated Systems Technician":         ["Automated Systems Analyst I/II", "Supervising Automated Systems Analyst I/II"],

    # Public Service
    "Animal Keeper I":                      ["Animal Keeper II", "Lead Animal Keeper", "Assistant Zoo Curator"],
    "Animal License Checker I":             ["Animal License Checker II", "Supervising Animal Control Officer"],
    "Animal Control Officer":               ["Animal Health Investigator", "Supervising Animal Control Officer"],
    "Sheriff's Communications Dispatcher Trainee": ["Sheriff's Communications Dispatcher", "Lead Sheriff's Communications Dispatcher", "Sheriff's Supervising Communications Dispatcher"],
}


def _connect():
    """Open a SQLite connection with foreign keys on and Row factory enabled."""
    db_path = os.path.join(PROJECT_ROOT, Config.DATABASE_PATH)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _apply_url(title):
    """Build a deep link to the SB County NeoGov careers portal pre-filled with the title."""
    return f"{GOVJOBS_BASE}?keywords={quote_plus(title)}"


def seed_programs(conn):
    """Insert the 10 CTE programs idempotently and return a name → id map."""
    print("\n-- CTE Programs")
    for name, desc, order in PROGRAMS:
        conn.execute("""
            INSERT INTO cte_programs (name, description, display_order)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
              description   = excluded.description,
              display_order = excluded.display_order
        """, (name, desc, order))
    rows = conn.execute("SELECT id, name FROM cte_programs").fetchall()
    program_ids = {r["name"]: r["id"] for r in rows}
    print(f"  {len(program_ids)} programs upserted")
    return program_ids


def seed_positions(conn, program_ids):
    """Insert all county_positions rows, replacing matching (title, program) pairs."""
    print("\n-- County positions")
    inserted = 0
    for program_name, code, title, union, grade, lo, hi, mqs, notes in POSITIONS:
        prog_id = program_ids.get(program_name)
        if prog_id is None:
            print(f"  ! Unknown program: {program_name} (skipping {title})")
            continue
        conn.execute("""
            INSERT INTO county_positions
              (job_code, title, cte_program_id, union_code, grade,
               min_hourly, max_hourly, mqs_text, notes, apply_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(title, cte_program_id) DO UPDATE SET
              job_code   = excluded.job_code,
              union_code = excluded.union_code,
              grade      = excluded.grade,
              min_hourly = excluded.min_hourly,
              max_hourly = excluded.max_hourly,
              mqs_text   = excluded.mqs_text,
              notes      = excluded.notes,
              apply_url  = excluded.apply_url
        """, (code, title, prog_id, union, grade, lo, hi, mqs, notes, _apply_url(title)))
        inserted += 1
    print(f"  {inserted} positions upserted")


def seed_ladders(conn):
    """Insert the career-ladder progression steps for every entry position."""
    print("\n-- Career ladders")
    # Wipe existing ladders so a re-run reflects the latest data verbatim.
    conn.execute("DELETE FROM position_ladder_steps")
    inserted = 0
    for entry_title, steps in LADDERS.items():
        row = conn.execute(
            "SELECT id FROM county_positions WHERE title = ?", (entry_title,)
        ).fetchone()
        if not row:
            print(f"  ! Entry position not found in catalog: {entry_title}")
            continue
        entry_id = row["id"]
        for i, step_title in enumerate(steps, start=2):  # step 1 = entry itself (implicit)
            conn.execute("""
                INSERT INTO position_ladder_steps
                  (entry_position_id, step_number, title)
                VALUES (?, ?, ?)
            """, (entry_id, i, step_title))
            inserted += 1
    print(f"  {inserted} ladder steps inserted")


def map_pathways_to_programs(conn):
    """Back-fill pathways.cte_program_id from the pathway's sector via SECTOR_TO_PROGRAM."""
    print("\n-- Pathway → program mapping")
    program_ids = {
        r["name"]: r["id"]
        for r in conn.execute("SELECT id, name FROM cte_programs").fetchall()
    }
    mapped   = 0
    unmapped = 0
    unmapped_sectors = set()
    rows = conn.execute("SELECT id, name, sector FROM pathways").fetchall()
    for r in rows:
        sector = (r["sector"] or "").strip()
        program_name = SECTOR_TO_PROGRAM.get(sector)
        if program_name and program_name in program_ids:
            conn.execute(
                "UPDATE pathways SET cte_program_id = ? WHERE id = ?",
                (program_ids[program_name], r["id"])
            )
            mapped += 1
        else:
            unmapped += 1
            if sector:
                unmapped_sectors.add(sector)
    print(f"  {mapped} pathways mapped, {unmapped} unmapped")
    if unmapped_sectors:
        print("  Unmapped sectors (no county program tied):")
        for s in sorted(unmapped_sectors):
            print(f"    - {s}")


def run():
    """End-to-end import: programs → positions → ladders → pathway mapping, all in one tx."""
    db_path = os.path.join(PROJECT_ROOT, Config.DATABASE_PATH)
    if not os.path.exists(db_path):
        print("Database not found. Run: python database/init_db.py")
        sys.exit(1)
    conn = _connect()
    try:
        program_ids = seed_programs(conn)
        seed_positions(conn, program_ids)
        seed_ladders(conn)
        map_pathways_to_programs(conn)
        conn.commit()
        print("\nCounty catalog import complete.")
    except Exception as e:
        conn.rollback()
        print(f"\nImport failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run()
