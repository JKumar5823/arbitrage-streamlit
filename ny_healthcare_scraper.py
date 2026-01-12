"""
NY Healthcare Facility Scraper
Collects names, emails, and phone numbers for healthcare facilities in New York State:
- Hospitals
- Outpatient Clinics
- Imaging/Radiology Centers

Data sources:
- NY State Department of Health Open Data Portal
- CMS (Centers for Medicare & Medicaid Services) Provider Data
"""

import streamlit as st
import requests
import pandas as pd
import io
from typing import Optional
import re


# NY State Health Data API endpoints (Socrata Open Data API)
NY_HEALTH_FACILITIES_API = "https://health.data.ny.gov/resource/vn5v-hh5r.json"  # Health Facility General Information

# CMS Provider Data API
CMS_HOSPITAL_API = "https://data.cms.gov/provider-data/api/1/datastore/query/xubh-q36u/0"
CMS_OUTPATIENT_API = "https://data.cms.gov/provider-data/api/1/datastore/query/4pq5-n9py/0"


def clean_phone(phone: str) -> str:
    """Clean and format phone number."""
    if not phone:
        return ""
    # Remove non-numeric characters
    digits = re.sub(r'\D', '', str(phone))
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    elif len(digits) == 11 and digits[0] == '1':
        return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    return phone


def clean_email(email: str) -> str:
    """Clean and validate email format."""
    if not email:
        return ""
    email = str(email).strip().lower()
    # Basic email validation
    if '@' in email and '.' in email:
        return email
    return ""


def fetch_ny_health_facilities(facility_type: str, limit: int = 5000) -> pd.DataFrame:
    """
    Fetch healthcare facilities from NY State Health Data Portal.

    Facility types in the dataset:
    - Hospital
    - Diagnostic and Treatment Center (Outpatient)
    - Ambulatory Surgery Center
    """
    try:
        # Build the URL with query parameters
        base_url = NY_HEALTH_FACILITIES_API

        # Map user-friendly types to API values
        type_mapping = {
            "hospitals": ["Hospital"],
            "outpatient_clinics": ["Diagnostic and Treatment Center", "Ambulatory Surgery Center"],
            "imaging_centers": ["Diagnostic and Treatment Center"]  # Imaging centers are often D&TCs
        }

        where_clause = "county IS NOT NULL"
        if facility_type in type_mapping:
            types = type_mapping[facility_type]
            type_filter = " OR ".join([f"description='{t}'" for t in types])
            where_clause += f" AND ({type_filter})"

        url = f"{base_url}?$limit={limit}&$where={requests.utils.quote(where_clause)}"

        response = requests.get(url, timeout=60)
        response.raise_for_status()
        data = response.json()

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)

        # Standardize column names (actual API field names)
        column_mapping = {
            'facility_name': 'Name',
            'address1': 'Address',
            'city': 'City',
            'county': 'County',
            'fac_zip': 'ZIP Code',
            'fac_phone': 'Phone',
            'description': 'Facility Type',
            'operator_name': 'Owner/Operator'
        }

        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})

        # Clean phone numbers
        if 'Phone' in df.columns:
            df['Phone'] = df['Phone'].apply(clean_phone)

        # Select relevant columns
        available_cols = [col for col in ['Name', 'Facility Type', 'Address', 'City', 'County',
                                          'ZIP Code', 'Phone', 'Owner/Operator'] if col in df.columns]
        df = df[available_cols]

        return df

    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching NY Health data: {e}")
        return pd.DataFrame()


def fetch_cms_hospitals_ny(limit: int = 2000) -> pd.DataFrame:
    """
    Fetch NY hospital data from CMS Hospital General Information dataset.
    This includes contact information like phone numbers.
    """
    try:
        # CMS API for Hospital General Information
        url = "https://data.cms.gov/provider-data/api/1/datastore/query/xubh-q36u/0"

        payload = {
            "conditions": [
                {
                    "property": "state",
                    "value": "NY",
                    "operator": "="
                }
            ],
            "limit": limit,
            "offset": 0
        }

        headers = {"Content-Type": "application/json"}
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        results = data.get('results', [])

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)

        # Map columns
        column_mapping = {
            'facility_name': 'Name',
            'address': 'Address',
            'city': 'City',
            'state': 'State',
            'zip_code': 'ZIP Code',
            'county_name': 'County',
            'phone_number': 'Phone',
            'hospital_type': 'Hospital Type',
            'hospital_ownership': 'Ownership'
        }

        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})

        if 'Phone' in df.columns:
            df['Phone'] = df['Phone'].apply(clean_phone)

        available_cols = [col for col in ['Name', 'Hospital Type', 'Address', 'City', 'County',
                                          'ZIP Code', 'Phone', 'Ownership'] if col in df.columns]
        df = df[available_cols]

        return df

    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching CMS hospital data: {e}")
        return pd.DataFrame()


def fetch_cms_imaging_centers_ny(limit: int = 5000) -> pd.DataFrame:
    """
    Fetch NY imaging/radiology centers from CMS data.
    Uses the Supplier Directory dataset which includes imaging facilities.
    """
    try:
        # CMS Physician Compare API - Imaging facilities
        url = "https://data.cms.gov/provider-data/api/1/datastore/query/mj5m-pzi6/0"

        payload = {
            "conditions": [
                {
                    "property": "state",
                    "value": "NY",
                    "operator": "="
                }
            ],
            "limit": limit,
            "offset": 0
        }

        headers = {"Content-Type": "application/json"}
        response = requests.post(url, json=payload, headers=headers, timeout=30)

        if response.status_code != 200:
            # Fallback to supplier data
            return fetch_imaging_from_suppliers()

        data = response.json()
        results = data.get('results', [])

        if not results:
            return fetch_imaging_from_suppliers()

        df = pd.DataFrame(results)
        return df

    except requests.exceptions.RequestException:
        return fetch_imaging_from_suppliers()


def fetch_imaging_from_suppliers() -> pd.DataFrame:
    """
    Alternative method to fetch imaging centers from IDTF (Independent Diagnostic Testing Facility) data.
    """
    try:
        # Try NY State data for diagnostic centers
        where_clause = "description='Diagnostic and Treatment Center'"
        url = f"{NY_HEALTH_FACILITIES_API}?$limit=5000&$where={requests.utils.quote(where_clause)}"

        response = requests.get(url, timeout=60)
        response.raise_for_status()
        data = response.json()

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)

        # Filter for imaging-related facilities
        imaging_keywords = ['imaging', 'radiology', 'radiolog', 'mri', 'ct scan', 'x-ray',
                           'xray', 'diagnostic imaging', 'ultrasound', 'mammograph', 'pet scan',
                           'nuclear medicine', 'fluoroscopy']

        if 'facility_name' in df.columns:
            mask = df['facility_name'].str.lower().str.contains('|'.join(imaging_keywords), na=False)
            df = df[mask]

        # Use correct column names from API
        column_mapping = {
            'facility_name': 'Name',
            'address1': 'Address',
            'city': 'City',
            'county': 'County',
            'fac_zip': 'ZIP Code',
            'fac_phone': 'Phone',
            'description': 'Facility Type'
        }

        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})

        if 'Phone' in df.columns:
            df['Phone'] = df['Phone'].apply(clean_phone)

        available_cols = [col for col in ['Name', 'Facility Type', 'Address', 'City', 'County',
                                          'ZIP Code', 'Phone'] if col in df.columns]
        df = df[available_cols]

        return df

    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching imaging centers: {e}")
        return pd.DataFrame()


def fetch_outpatient_clinics_ny(limit: int = 5000) -> pd.DataFrame:
    """
    Fetch NY outpatient clinics from NY State Health Data.
    """
    try:
        where_clause = "description='Diagnostic and Treatment Center' OR description='Ambulatory Surgery Center'"
        url = f"{NY_HEALTH_FACILITIES_API}?$limit={limit}&$where={requests.utils.quote(where_clause)}"

        response = requests.get(url, timeout=60)
        response.raise_for_status()
        data = response.json()

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)

        # Use correct column names from API
        column_mapping = {
            'facility_name': 'Name',
            'address1': 'Address',
            'city': 'City',
            'county': 'County',
            'fac_zip': 'ZIP Code',
            'fac_phone': 'Phone',
            'description': 'Facility Type',
            'operator_name': 'Owner/Operator'
        }

        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})

        if 'Phone' in df.columns:
            df['Phone'] = df['Phone'].apply(clean_phone)

        available_cols = [col for col in ['Name', 'Facility Type', 'Address', 'City', 'County',
                                          'ZIP Code', 'Phone', 'Owner/Operator'] if col in df.columns]
        df = df[available_cols]

        return df

    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching outpatient clinic data: {e}")
        return pd.DataFrame()


def search_facilities(df: pd.DataFrame, search_term: str) -> pd.DataFrame:
    """Search facilities by name or location."""
    if not search_term or df.empty:
        return df

    search_term = search_term.lower()
    mask = pd.Series([False] * len(df))

    for col in df.columns:
        if df[col].dtype == 'object':
            mask |= df[col].astype(str).str.lower().str.contains(search_term, na=False)

    return df[mask]


def filter_by_county(df: pd.DataFrame, county: str) -> pd.DataFrame:
    """Filter facilities by county."""
    if not county or county == "All Counties" or df.empty:
        return df

    if 'County' in df.columns:
        return df[df['County'].str.upper() == county.upper()]
    return df


# NY Counties list
NY_COUNTIES = [
    "All Counties", "Albany", "Allegany", "Bronx", "Broome", "Cattaraugus", "Cayuga",
    "Chautauqua", "Chemung", "Chenango", "Clinton", "Columbia", "Cortland", "Delaware",
    "Dutchess", "Erie", "Essex", "Franklin", "Fulton", "Genesee", "Greene", "Hamilton",
    "Herkimer", "Jefferson", "Kings", "Lewis", "Livingston", "Madison", "Monroe",
    "Montgomery", "Nassau", "New York", "Niagara", "Oneida", "Onondaga", "Ontario",
    "Orange", "Orleans", "Oswego", "Otsego", "Putnam", "Queens", "Rensselaer", "Richmond",
    "Rockland", "Saratoga", "Schenectady", "Schoharie", "Schuyler", "Seneca", "St Lawrence",
    "Steuben", "Suffolk", "Sullivan", "Tioga", "Tompkins", "Ulster", "Warren", "Washington",
    "Wayne", "Westchester", "Wyoming", "Yates"
]


# --- Streamlit App ---
def main():
    st.set_page_config(
        page_title="NY Healthcare Facility Finder",
        page_icon="🏥",
        layout="wide"
    )

    st.title("🏥 New York Healthcare Facility Finder")
    st.markdown("""
    Find contact information for healthcare facilities across New York State.
    Data sourced from NY State Department of Health and CMS public datasets.
    """)

    # Sidebar for filters
    st.sidebar.header("Filters")

    facility_type = st.sidebar.selectbox(
        "Facility Type",
        ["All Types", "Hospitals", "Outpatient Clinics", "Imaging/Radiology Centers"]
    )

    county_filter = st.sidebar.selectbox("County", NY_COUNTIES)

    search_term = st.sidebar.text_input("Search by Name or Location", "")

    # Fetch data based on selection
    if st.sidebar.button("🔍 Search Facilities", type="primary"):
        with st.spinner("Fetching healthcare facility data..."):

            all_facilities = []

            if facility_type == "Hospitals" or facility_type == "All Types":
                st.subheader("🏨 Hospitals")
                hospitals_df = fetch_cms_hospitals_ny()

                if not hospitals_df.empty:
                    # Also get NY state data
                    ny_hospitals = fetch_ny_health_facilities("hospitals")
                    if not ny_hospitals.empty:
                        hospitals_df = pd.concat([hospitals_df, ny_hospitals], ignore_index=True)
                        hospitals_df = hospitals_df.drop_duplicates(subset=['Name'], keep='first')
                else:
                    hospitals_df = fetch_ny_health_facilities("hospitals")

                # Apply filters
                if county_filter != "All Counties":
                    hospitals_df = filter_by_county(hospitals_df, county_filter)
                if search_term:
                    hospitals_df = search_facilities(hospitals_df, search_term)

                if not hospitals_df.empty:
                    st.success(f"Found {len(hospitals_df)} hospitals")
                    st.dataframe(hospitals_df, use_container_width=True)
                    all_facilities.append(hospitals_df.assign(Category='Hospital'))

                    # Download button
                    output = io.BytesIO()
                    hospitals_df.to_excel(output, index=False, engine='openpyxl')
                    output.seek(0)
                    st.download_button(
                        label="📥 Download Hospitals Excel",
                        data=output,
                        file_name="ny_hospitals.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.warning("No hospitals found matching your criteria.")

                st.divider()

            if facility_type == "Outpatient Clinics" or facility_type == "All Types":
                st.subheader("🩺 Outpatient Clinics")
                clinics_df = fetch_outpatient_clinics_ny()

                # Apply filters
                if county_filter != "All Counties":
                    clinics_df = filter_by_county(clinics_df, county_filter)
                if search_term:
                    clinics_df = search_facilities(clinics_df, search_term)

                if not clinics_df.empty:
                    st.success(f"Found {len(clinics_df)} outpatient clinics")
                    st.dataframe(clinics_df, use_container_width=True)
                    all_facilities.append(clinics_df.assign(Category='Outpatient Clinic'))

                    output = io.BytesIO()
                    clinics_df.to_excel(output, index=False, engine='openpyxl')
                    output.seek(0)
                    st.download_button(
                        label="📥 Download Clinics Excel",
                        data=output,
                        file_name="ny_outpatient_clinics.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.warning("No outpatient clinics found matching your criteria.")

                st.divider()

            if facility_type == "Imaging/Radiology Centers" or facility_type == "All Types":
                st.subheader("📷 Imaging/Radiology Centers")
                imaging_df = fetch_imaging_from_suppliers()

                # Apply filters
                if county_filter != "All Counties":
                    imaging_df = filter_by_county(imaging_df, county_filter)
                if search_term:
                    imaging_df = search_facilities(imaging_df, search_term)

                if not imaging_df.empty:
                    st.success(f"Found {len(imaging_df)} imaging/radiology centers")
                    st.dataframe(imaging_df, use_container_width=True)
                    all_facilities.append(imaging_df.assign(Category='Imaging/Radiology'))

                    output = io.BytesIO()
                    imaging_df.to_excel(output, index=False, engine='openpyxl')
                    output.seek(0)
                    st.download_button(
                        label="📥 Download Imaging Centers Excel",
                        data=output,
                        file_name="ny_imaging_centers.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.warning("No imaging/radiology centers found matching your criteria.")

            # Combined download for all facility types
            if all_facilities and facility_type == "All Types":
                st.divider()
                st.subheader("📦 Download All Facilities")
                combined_df = pd.concat(all_facilities, ignore_index=True)
                output = io.BytesIO()
                combined_df.to_excel(output, index=False, engine='openpyxl')
                output.seek(0)
                st.download_button(
                    label="📥 Download All Facilities Excel",
                    data=output,
                    file_name="ny_all_healthcare_facilities.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary"
                )

    # Quick Stats section
    st.sidebar.divider()
    st.sidebar.markdown("### About")
    st.sidebar.info("""
    **Data Sources:**
    - NY State DOH Health Facility Database
    - CMS Hospital Compare Data
    - CMS Provider Data Catalog

    **Note:** Email addresses are not typically included in public facility datasets.
    Contact facilities directly for specific email addresses.
    """)


if __name__ == "__main__":
    main()
