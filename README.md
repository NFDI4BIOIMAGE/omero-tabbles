# Annotations from Tabbles
This is an OMERO.web script to create Annotations in [OMERO](https://www.openmicroscopy.org/omero/) based on Tags from [Tabbles](https://tabbles.net/).

# Purpose
With the rapid rise of Image data volume Research Data Management (RDM) becomes ever more important.<br>
The inherent [FAIR](https://www.nature.com/articles/sdata201618) (Findability, Accessibility, Interoperability, Reusability) criteria can be met by utilizing open source tools like OMERO, which enjoys high adaptation rates throughout the BioImage community.

To exploit OMEROs full potential Image data has to be annotated with relevant Metadata.<br>
For now this mostly happens in the form of Key-Value Pairs (MapAnnotations in OMERO) and Tags (TagAnnotations in OMERO).<br>
The process to create suitable Annotations is tedious at the moment causing many users to shy away from it, which in turn severely limits the possible benefits of OMERO for them.

Our aim is to provide a workflow optimized for user adaptation by lowering the entry-barrier as much as possible while still providing the full functionality and possibility to scale up.

# TL;DR How To
The workflow consists of two steps.
1. Add Tabbles-tags to individual images or whole folders of images in Windows with a simple right-click (context menu) or even automatically with Auto-tagging rules.
2. Run the OMERO.web script to generate OMERO Annotations out of Tabbles-tags.

# How To

* Assumptions:
    * You are connected to your Tabbles server.
    * You uploaded the Images to OMERO.
* In your Explorer select any file or folder you want to tag, right-click > 'Tag File'
* In the small window that opens up select which tags you want to add.
* Log into your OMERO and select the Images/Datasets/Projects you want to annotate.
* Run the `Annotations_from_Tabbles.py` script.
* Enjoy 🙂

# Details
__DISCLAIMER!__ Tabbles is a __proprietary__ software! The [licensing costs](https://tabbles.net/buy-tabbles/) are not too high though.<br>
MSSQL also is proprietary, but the free version will be enough for purposes.

Tabbles allows to tag any file or folder in Windows.<br>
It also allows for the creation of nested tags which in turn allows the general structure `Namespace-tag > Key-tag > Value-tag`.<br>
This might also be interesting with regards to the [ISA](https://isa-specs.readthedocs.io/en/latest/isamodel.html) (Investigation-Study-Assay) or [ARC](https://www.nfdi4plants.de/content/learn-more/annotated-research-context.html) (Annotated Research Context) structure.<br>
Additionally, the [REMBI](https://www.nature.com/articles/s41592-021-01166-8) (Recommended Metadata for Biological Images) metadata standard also operates with a double-nested structure.<br>
In contrast to most other tagging applications, Tabbles' Data is stored in a MSSQL (Microsoft SQL) database, so we can access it from the OMERO server via the OMERO.web script.<br>
To allow multiple users/groups to access the same Tabbles database and therefore use the same tags we hosted a MSSQL instance on a Ubuntu VM in our University cloud in Muenster.<br>
The inherent limitations that occur from running it on Linux are not relevant to our use case.<br>

Tabbles allows for a fine grained user and group control and even LDAP authentication.<br>
Tabbles-tags can be shared between groups.<br>
The proposed structure is a general set of Namespace-tags and some Key-tags which are shared with everyone.<br>
As one Tabbles user can be logged in at several workstations, we propose only one Tabbles user per research workgroup, so every  group can have its own individual Key-tags and Value-tags.<br>

We query the SQL database to get the tags and their nested structure, which allow us to turn them into MapAnnotations and TagAnnotations in OMERO.<br>
If [OMERO.mapr](https://github.com/ome/omero-mapr) is installed one can additionally utilize the Namespace-tag level to create MapAnnotations as can be seen in the [IDR](https://idr.openmicroscopy.org/webclient/?show=screen-51), including headers, search functionality and icons with URL links.

# Limitations
* Tabbles is a proprietary software with a limited trial-period (30 days).
* Tabbles works only with Windows, as it is closely tied to the Windows File Manager.
* The current path of the image has to be the same as the `ImportPath` in OMERO, i.e. __do not move your images after uploading them!__ (A future  workaround feature to provide a new path in the script is planned).
* Tags are not allowed to start with "_", because Tabbles-internal tags start like this and we have to filter them out.
* Namespace-level Tags can consist only of the actual Namespace name (e.g. Biosample, Specimen,...) and a non-alphabetical (symbols and 
    numbers) prefix and suffix e.g. "03_Biosample" or "0012+Biosample+++++".
* OMERO.mapr Namespaces must be all lowercase.
* For security reasons the login data for the MSSQL server has to be stored in a .json file `/opt/omero/MSSQL_login.json` in the structure:
```
{"DRIVER": "{ODBC Driver 18 for SQL Server}", "SERVER": "<server ip>", "DATABASE": "<database name>", "UID": "<user name to access MSSQL>", "PWD": "<password for that user>"}
```
* The MSSQL database that is accessed defaults to `tabbles_production` (which can be changed manually in the code and the `MSSQL_login.json`)


# Installation
## User

#### Tabbles: 
Follow the installation instructions on the [website](https://tabbles.net/download-page/).
Log in with the credentials provided by your System Admin.

## System Admin
#### OMERO.mapr: 
Follow the installation guide on the [GitHub](https://github.com/ome/omero-mapr). 
Only Namespaces and Keys defined in the config under "ns" and "all" respectively, can utilize the functionality of OMERO.mapr, namely the search function of the values and the possibility to add a URL Key-Value pair to create a hyperlink-thumbnail:

![](https://github.com/MuensterImagingNetwork/annotations_from_tabbles/blob/dev/Capture.PNG?raw=true) 

The most important part is to configure the Namespaces correctly, even if some Keys are not in the configuration they will still be displayed under their correct Namespace "paragraph" they just cannot benefit from the full OMERO.mapr functionality which might not be needed for every Key anyways.<br>
Configure the settings according to your used Tabbles Namespace-level tags, i.e. the "ns" entry has to contain the "stripped" Namespace-tag from Tabbles. To better visualize this, here an example:

|case|Tabbles Tag names | OMERO.mapr Namespaces|
|----|----|---|
|01|'01_Essentials' |omero.mapr_essentials|
|02|'02_Biosample' |mapr.BioSample|
|03|'03_ELN' |03_eln|
|04|'04_Supplementary' |04_mapr.Suppl.|

The cases 01 and 02 will work, as `"essentials" in "omero.mapr_essentials" = True` same as  `"eln" in "03_eln"`. Case 04 will not work as `"supplementary"` is not in `"04_mapr.Suppl."` and additionally the OMERO.mapr Namespace is not all lowercase, the same applies to `"biosample" in "mapr.BioSample"`.

#### Tabbles: 
Follow the installation instructions on the [website](https://tabbles.net/download-page/) and then initialize the Tabbles database by following the [HowTos](https://tabbles.net/how-tos/) on the website.<br>
There is an extensive documentation (for a proprietary Software) and in-depth explanation of the workings behind Tabbles on their website.

#### MSSQL: 
Follow the [official installation instructions](https://learn.microsoft.com/en-us/sql/linux/sql-server-linux-setup?view=sql-server-ver16). The "Express" License (equaling the free version) will be enough for the workload that Tabbles puts on the server from our experience.<br>
It is highly advised to utilize the SQL Server Management Studio (SSMS) to interact with the MSSQL instance. A free version can be installed from [here](https://learn.microsoft.com/de-de/sql/ssms/download-sql-server-management-studio-ssms?view=sql-server-ver16).<br>
To be able to connect to the MSSQL instance and read the necessary data we have to create a special login and subsequent user for the Tabbles database.
1) Create a new "Login" under "Databases"->"Security"  e.g. `<python-user>` with password  `<python-password>`
2) Create a new "User", under "Databases"->"your-tabbles-database"->"Security"->"Users" right-click "New User" and use the login `<python-user>` for that user
3) Then run the T-SQL command:  
    ```
    Use your-tabbles-database
    EXEC sp_addrolemember db_datareader , python-user
    ```
    to grant `<python-user>` access to read all tables in the database.<br>  

#### Enabling the OMERO server to connect to MSSQL:
On the OMERO server as `<omero-server>` user: 
```
$pip install pyodbc
```
then follow the [official installation instructions](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server?view=sql-server-ver16&tabs=redhat18-install%2Credhat17-install%2Cdebian8-install%2Credhat7-13-install%2Crhel7-offline#18) to install Microsoft ODBC drivers (with the latest version of MSSQL server we use Microsoft ODBC 18).



