"""
PowerWatch
build_powerwatch.py
Builds the PowerWatch database from various data sources.
- Log build to POWERWATCH_BUILD_LOG_FILE
- Use country and fuel information as specified in powerwatch.py
"""

import csv
import time
import argparse
import sys, os

sys.path.insert(0, os.pardir)
import powerwatch as pw

### PARAMETERS ###
COUNTRY_DATABASE_FILE = pw.make_file_path(fileType = "src_bin", filename = "COUNTRY-Database.bin")
WRI_DATABASE_FILE = pw.make_file_path(fileType = "src_bin", filename = "WRI-Database.bin")
GEO_DATABASE_FILE = pw.make_file_path(fileType = "src_bin", filename = "GEODB-Database.bin")
CARMA_DATABASE_FILE = pw.make_file_path(fileType = "src_bin", filename = "CARMA-Database.bin")
SOURCEWATCH_DATABASE_FILE = pw.make_file_path(fileType = "src_bin", filename = "SRCWT-Database.bin")
POWERWATCH_CSV_SAVEFILE = pw.make_file_path(fileType = "output", filename = "powerwatch_data.csv")
POWERWATCH_BUILD_LOG_FILE = pw.make_file_path(fileType = "output", filename = "powerwatch_build_log.txt")
POWERWATCH_CSV_DUMPFILE = pw.make_file_path(fileType = "output", filename = "powerwatch_data_dump.csv")
MINIMUM_CAPACITY_MW = 1

parser = argparse.ArgumentParser()
parser.add_argument("--dump", help = "dump all the data", action="store_true")
DATA_DUMP = True if parser.parse_args().dump else False

# open log file
f_log = open(POWERWATCH_BUILD_LOG_FILE,'a')
f_log.write('Starting PowerWatch build run at {0}.\n'.format(time.ctime()))

# print summary
print("Starting PowerWatch build; minimum plant size: {0} MW.".format(MINIMUM_CAPACITY_MW))

# make country dictionary
country_dictionary = pw.make_country_dictionary()

# make powerplants dictionary
powerwatch_database = {}
powerwatch_datadump = {}

# make plant condcordance dictionary
plant_concordance = pw.make_plant_concordance()
print("Loaded concordance file with {0} entries.".format(len(plant_concordance)))
carma_id_used = []	# Record matched carma_ids

# STEP 0: Read in source databases.
# Identify countries with automated data from .has_api flag.
print("Loading source databases...")
country_databases = {}
for country_name,country in country_dictionary.iteritems():
	if country.has_api == 1:
		country_code = country.iso_code
		database_filename = COUNTRY_DATABASE_FILE.replace("COUNTRY", country_code)
		country_databases[country_name] = pw.load_database(database_filename)
		print("Loaded {0} plants from {1} database.".format(len(country_databases[country_name]),country_name))

# Load multi-country databases.
wri_database = pw.load_database(WRI_DATABASE_FILE)
print("Loaded {0} plants from WRI database.".format(len(wri_database)))
geo_database = pw.load_database(GEO_DATABASE_FILE)
print("Loaded {0} plants from GEO database.".format(len(geo_database)))
carma_database = pw.load_database(CARMA_DATABASE_FILE)
print("Loaded {0} plants from CARMA database.".format(len(carma_database)))
sourcewatch_database = pw.load_database(SOURCEWATCH_DATABASE_FILE)
print("Loaded {0} plants from SourceWatch database.".format(len(sourcewatch_database)))

# Track counts using a dict with keys corresponding to each data source
db_sources = country_databases.keys()
db_sources.extend(["WRI","GEO","SourceWatch","WRI with GEO lat/long data","WRI with CARMA lat/long data"])
database_additions = {dbname: {'count': 0, 'capacity': 0} for dbname in db_sources}

# STEP 1: Add all data (capacity >= 1MW) from countries with automated data to PowerWatch
for country_name, database in country_databases.iteritems():
	country_code = country_dictionary[country_name].iso_code
	print("Adding plants from {0}.".format(country_dictionary[country_name].primary_name))
	coordinate_source = country_name + u" national data"
	for plant_id,plant in database.iteritems():
		plant.coord_source = coordinate_source
		powerwatch_datadump[plant_id] = plant
		if plant.capacity >= MINIMUM_CAPACITY_MW:
			if (plant.location.latitude and plant.location.longitude) and (plant.location.latitude != 0 and plant.location.longitude != 0):
				powerwatch_database[plant_id] = plant
				database_additions[country_name]['count'] += 1
				database_additions[country_name]['capacity'] += plant.capacity
			else:
				plant.idnr = plant_id + u",No"
		else:
			plant.idnr = plant_id + u",No"

# STEP 2: Go through WRI database and triage plants
print("Adding plants from WRI internal database.")
for plant_id, plant in wri_database.iteritems():
	# Cases to skip
	if not isinstance(plant, pw.PowerPlant):
		f_log.write('Error: plant {0} is not a PowerPlant object.\n'.format(plant_id))
		continue
	if plant.country not in country_dictionary.keys():
		f_log.write('Error: country {0} not recognized.\n'.format(plant.country))
		continue
	# Skip plants with data loaded directly from a national API
	if country_dictionary[plant.country].has_api:
		continue
	# Skip plants in countries where we will use GEO data
	if country_dictionary[plant.country].use_geo:
		continue

	powerwatch_datadump[plant_id] = plant

	# Skip plants below minimum capacity cutoff
	if plant.capacity < MINIMUM_CAPACITY_MW:
		continue

	# STEP 2.1: If plant has lat/long information, add it to PowerWatch
	if (plant.location.latitude and plant.location.longitude) and (plant.location.latitude != 0 and plant.location.longitude != 0):
		plant.idnr = plant_id
		plant.coord_source = u"WRI data"
		powerwatch_database[plant_id] = plant
		database_additions['WRI']['count'] += 1
		database_additions['WRI']['capacity'] += plant.capacity
		continue

	# STEP 2.2: If plant is matched to GEO, add to PowerWatch using GEO lat/long
	if plant_id in plant_concordance:
		matching_geo_id = plant_concordance[plant_id]['geo_id']
		if matching_geo_id:
			try:
				plant.location = geo_database[matching_geo_id].location
			except:
				f_log.write("Matching error: no GEO location for WRI plant {0}, GEO plant {1}\n".format(plant_id,matching_geo_id))
				continue
			if plant.location.latitude and plant.location.longitude:
				plant.idnr = plant_id
				plant.coord_source = u"GEO data"
				powerwatch_database[plant_id] = plant
				database_additions["WRI with GEO lat/long data"]['count'] += 1
				database_additions["WRI with GEO lat/long data"]['capacity'] += plant.capacity
				continue

	# STEP 2.3: If plant is matched to CARMA, add to PowerWatch using CARMA lat/long
	if plant_id in plant_concordance:
		matching_carma_id = plant_concordance[plant_id]['carma_id']
		if matching_carma_id:
			try:
				plant.location = carma_database[matching_carma_id].location
			except:
				f_log.write("Matching error: no CARMA location for WRI plant {0}, CARMA plant {1}\n".format(plant_id,matching_carma_id))
				continue
			if plant.location.latitude and plant.location.longitude:
				plant.idnr = plant_id
				plant.coord_source = u"CARMA data"
				powerwatch_database[plant_id] = plant
				carma_id_used.append(matching_carma_id)
				database_additions["WRI with CARMA lat/long data"]['count'] += 1
				database_additions["WRI with CARMA lat/long data"]['capacity'] += plant.capacity
				continue
	# Note: Would eventually like to refine CARMA locations - known to be inaccurate in some cases

# STEP 3: Go through GEO database and add plants from small countries
# Plants in this database only have numeric ID (no prefix) because of concordance matching
for plant_id,plant in geo_database.iteritems():
	# Catch errors if plants do not have a correct country assigned
	powerwatch_datadump[plant_id] = plant
	if plant.country not in country_dictionary.keys():
		print("Plant {0} has country {1} - not found.".format(plant_id,plant.country))
		continue
	if country_dictionary[plant.country].use_geo:
		if (plant.location.latitude and plant.location.longitude) and (plant.location.latitude != 0 and plant.location.longitude != 0):
			plant.coord_source = u"GEO data"
			plant.idnr = plant_id
			powerwatch_database[plant_id] = plant
			database_additions['GEO']['count'] += 1
			try:
				database_additions['GEO']['capacity'] += plant.capacity
			except:
				f_log.write("Attribute Warning: GEO plant {0} does not have valid capacity information <{1}>\n".format(plant_id, plant.capacity))

# STEP 4: Add China coal plants from SourceWatch
for plant_id,plant in sourcewatch_database.iteritems():
	powerwatch_datadump[plant_id] = plant
	if (plant.location.latitude and plant.location.longitude) and (plant.location.latitude != 0 and plant.location.longitude != 0):
		plant.coord_source = u"SourceWatch data"
		powerwatch_database[plant_id] = plant
		database_additions['SourceWatch']['count'] += 1
		database_additions['SourceWatch']['capacity'] += plant.capacity

# STEP 5: Estimate generation for plants without reported generation for target year
count_plants_with_generation = 0
#for plant_id,plant in powerwatch_database.iteritems():
#	if plant.generation != pw.NO_DATA_OTHER:
#		count_plants_with_generation += 1
#print('Of {0} total plants, {1} have reported generation data.'.format(len(powerwatch_database),count_plants_with_generation))
print('Estimating generation...')
estimated_plants = pw.estimate_generation(powerwatch_database)
print('...estimated for {0} plants.'.format(estimated_plants))

# STEP 6: Write PowerWatch
for dbname, data in database_additions.iteritems():
	print("Added {0} plants ({1} MW) from {2}.".format(data['count'], data['capacity'], dbname))

f_log.close()
print("Loaded {0} plants to PowerWatch.".format(len(powerwatch_database)))
pw.write_csv_file(powerwatch_database,POWERWATCH_CSV_SAVEFILE)
print("PowerWatch built.")

# STEP 7: Dump Data
if DATA_DUMP:
	print("Dumping all the data...")
	# STEP 7.1: Label plants in datadump
	pw_idnrs = powerwatch_database.keys()
	for plant_id,plant in powerwatch_datadump.iteritems():
		if plant_id in pw_idnrs:
			plant.idnr = plant_id + ",Yes"
		else:
			plant.idnr = plant_id + ",No"

	# STEP 7.2: Add unused CARMA plants
	for plant_id,plant in carma_database.iteritems():
		plant.coord_source = u"CARMA data"
		if plant_id in carma_id_used:
			continue
		else:
			plant.idnr = plant_id + ",No"
			powerwatch_datadump[plant_id] = plant

	# STEP 8: Dump data
	print("Dumped {0} plants.".format(len(powerwatch_datadump)))
	pw.write_csv_file(powerwatch_datadump,POWERWATCH_CSV_DUMPFILE,dump=True)
	print("Data dumped.")

print("Finished.")
