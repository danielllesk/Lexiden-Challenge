import json
from typing import Dict, Any, Optional
import re

# for extracted information and generated documents
extracted_data_store: Dict[str, Any] = {}
document_store: Dict[str, str] = {}

def get_function_definitions():
    """Return the function definitions for OpenAI function calling"""
    return [
        {
            "type": "function",
            "function": {
                "name": "extract_information",
                "description": "Extract and store structured information from the conversation for document generation. ALWAYS call this function as you collect information from the user. The data is saved to a session store for later use.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "extracted_data": {
                            "type": "object",
                            "description": "A structured object containing all relevant information extracted from the conversation. For NDAs use: disclosing_party, receiving_party, effective_date, purpose, term_years, jurisdiction. For Employment Agreements use: employee_name, position, start_date, salary."
                        },
                        "document_type": {
                            "type": "string",
                            "description": "The type of legal document being created (e.g., 'NDA', 'Employment Agreement', 'Director Appointment Resolution')"
                        }
                    },
                    "required": ["extracted_data", "document_type"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "generate_document",
                "description": "Generate a complete legal document. CRITICAL: You MUST pass the complete extracted_data object containing ALL fields you collected from the user. Do NOT call this function with an empty object {}.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "document_type": {
                            "type": "string",
                            "description": "The type of legal document to generate (e.g., 'NDA', 'Employment Agreement')"
                        },
                        "extracted_data": {
                            "type": "object",
                            "description": "REQUIRED: Complete data object containing ALL fields collected from the user. For NDA: disclosing_party, receiving_party, effective_date, purpose, term_years, jurisdiction. You MUST include all fields here."
                        }
                    },
                    "required": ["document_type", "extracted_data"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "apply_edits",
                "description": "Apply edits or modifications to an existing document based on user requests. Use this when the user wants to change specific parts of a generated document.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Identifier for the document to edit (use 'current' if only one document exists)"
                        },
                        "edit_description": {
                            "type": "string",
                            "description": "Description of what needs to be changed"
                        },
                        "new_values": {
                            "type": "object",
                            "description": "New values or changes to apply to the document"
                        }
                    },
                    "required": ["edit_description", "new_values"]
                }
            }
        }
    ]


def validate_required_fields(document_type: str, data: Dict[str, Any]) -> Optional[str]:
    """Validate that all required fields are present for a document type.
    Returns None if valid, or an error message string if validation fails."""
    
    required_fields = {}
    
    if document_type.lower() == "nda" or "non-disclosure" in document_type.lower():
        required_fields = {
            'disclosing_party': ['disclosing_party', 'disclosing_party_name', 'party1', 'company_name'],
            'receiving_party': ['receiving_party', 'receiving_party_name', 'party2', 'recipient'],
            'effective_date': ['effective_date', 'date', 'start_date'],
            'purpose': ['purpose', 'purpose_of_disclosure', 'reason'],
            'term_years': ['term', 'term_years', 'duration', 'period'],
            'jurisdiction': ['jurisdiction', 'state', 'governing_law']
        }
    elif "employment" in document_type.lower():
        required_fields = {
            'employee_name': ['employee_name', 'name'],
            'position': ['position', 'title', 'role'],
            'start_date': ['start_date', 'effective_date', 'date'],
            'salary': ['salary', 'compensation', 'pay']
        }
    elif "director" in document_type.lower() or "appointment" in document_type.lower():
        required_fields = {
            'director_name': ['director_name', 'name'],
            'effective_date': ['effective_date', 'date']
        }
    
    # Check if at least one variant of each required field is present
    missing_fields = []
    for field_name, field_variants in required_fields.items():
        if not any(data.get(variant) for variant in field_variants):
            missing_fields.append(field_name)
    
    if missing_fields:
        return f"ERROR: Missing required fields for {document_type}: {', '.join(missing_fields)}. Please provide all required information before generating the document."
    
    return None


def extract_information(extracted_data: Dict[str, Any], document_type: str) -> Dict[str, Any]:
    """Extract and store information from conversation."""
    session_id = "default"  # in production this would probably be per-user/session
    
    if session_id not in extracted_data_store:
        extracted_data_store[session_id] = {}
    
    # combine the  new data with existing data
    if document_type not in extracted_data_store[session_id]:
        extracted_data_store[session_id][document_type] = {}
    
    extracted_data_store[session_id][document_type].update(extracted_data)
    
    return {
        "status": "success",
        "message": f"Information extracted for {document_type}",
        "extracted_data": extracted_data_store[session_id][document_type]
    }


def generate_document(document_type: str, extracted_data: Dict[str, Any], conversation_history: list = None) -> str:
    """Generate a legal document from extracted data."""
    import os
    from openai import OpenAI
    
    session_id = "default"
    document_id = f"{document_type}_{len(document_store)}"
    
    # FALLBACK: If extracted_data is empty and we have conversation history, try to extract data automatically
    if (not extracted_data or not any(extracted_data.values())) and conversation_history:
        print("DEBUG - Extracted data is empty, attempting fallback extraction from conversation history")
        try:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            
            # Build a prompt to extract data from conversation based on document type
            if document_type.lower() == "nda" or "non-disclosure" in document_type.lower():
                field_template = '{"disclosing_party": "", "receiving_party": "", "effective_date": "", "purpose": "", "term_years": "", "jurisdiction": ""}'
            elif "employment" in document_type.lower():
                field_template = '{"employee_name": "", "position": "", "start_date": "", "salary": ""}'
            elif "director" in document_type.lower() or "appointment" in document_type.lower():
                field_template = '{"director_name": "", "effective_date": "", "committees": []}'
            else:
                field_template = '{}'
            
            extraction_prompt = f"""Extract the following information for a {document_type} from the conversation below.
Return ONLY a JSON object with the exact structure shown (use null for missing fields, do NOT add extra nesting):

{field_template}

Conversation:
"""
            for msg in conversation_history[-10:]:  # Last 10 messages
                if msg.get("role") == "user":
                    extraction_prompt += f"User: {msg.get('content', '')}\n"
                elif msg.get("role") == "assistant" and msg.get("content"):
                    extraction_prompt += f"Assistant: {msg.get('content', '')}\n"
            
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": extraction_prompt}],
                temperature=0.3
            )
            
            import json
            extracted_text = response.choices[0].message.content.strip()
            # Remove markdown code blocks if present
            if "```json" in extracted_text:
                extracted_text = extracted_text.split("```json")[1].split("```")[0].strip()
            elif "```" in extracted_text:
                extracted_text = extracted_text.split("```")[1].split("```")[0].strip()
            
            extracted_data = json.loads(extracted_text)
            print(f"DEBUG - Fallback extraction successful: {extracted_data}")
            
            # Store the extracted data
            extract_information(extracted_data, document_type)
            
        except Exception as e:
            print(f"DEBUG - Fallback extraction failed: {str(e)}")
            # Continue with empty data, will hit validation error below
    
    if session_id in extracted_data_store and document_type in extracted_data_store[session_id]:
        if extracted_data:
            merged_data = {**extracted_data_store[session_id][document_type], **extracted_data}
        else:
            merged_data = extracted_data_store[session_id][document_type]
    else:
        merged_data = extracted_data
        if session_id not in extracted_data_store:
            extracted_data_store[session_id] = {}
        extracted_data_store[session_id][document_type] = merged_data
    
    print(f"DEBUG - Document Type: {document_type}")
    print(f"DEBUG - Extracted Data Passed: {extracted_data}")
    print(f"DEBUG - Session Store for {document_type}: {extracted_data_store.get(session_id, {}).get(document_type, {})}")
    print(f"DEBUG - Merged Data: {merged_data}")
    
    if not merged_data or all(not v for v in merged_data.values()):
        return f"ERROR: No data found for {document_type}. Please call extract_information first with all required fields."
    
    validation_error = validate_required_fields(document_type, merged_data)
    if validation_error:
        print(f"DEBUG - Validation Error: {validation_error}")
        return validation_error
    
    document = ""
    
    if document_type.lower() == "nda" or "non-disclosure" in document_type.lower():
        # Try multiple possible field names for each piece of data
        disclosing_party = (
            merged_data.get('disclosing_party') or 
            merged_data.get('disclosing_party_name') or
            merged_data.get('party1') or
            merged_data.get('company_name') or
            '**Disclosing Party Name Missing**'
        )
        
        receiving_party = (
            merged_data.get('receiving_party') or 
            merged_data.get('receiving_party_name') or
            merged_data.get('party2') or
            merged_data.get('recipient') or
            '**Receiving Party Name Missing**'
        )
        
        effective_date = (
            merged_data.get('effective_date') or 
            merged_data.get('date') or 
            merged_data.get('start_date') or
            '[EFFECTIVE DATE]'
        )
        
        term_years = (
            merged_data.get('term') or 
            merged_data.get('term_years') or 
            merged_data.get('duration') or
            merged_data.get('period') or
            '0'
        )
        
        # Convert term to string if it's a number
        term_years = str(term_years)
        
        jurisdiction = (
            merged_data.get('jurisdiction') or 
            merged_data.get('state') or 
            merged_data.get('governing_law') or
            '[JURISDICTION/STATE]'
        )
        
        purpose = (
            merged_data.get('purpose') or 
            merged_data.get('purpose_of_disclosure') or
            merged_data.get('reason') or
            '**Purpose of Disclosure Missing**'
        )
        
        document = f"""
NON-DISCLOSURE AGREEMENT

This Non-Disclosure Agreement ("Agreement") is entered into on {effective_date} (the "Effective Date") by and between:

DISCLOSING PARTY: {disclosing_party}
("Disclosing Party")

RECEIVING PARTY: {receiving_party}
("Receiving Party")

RECITALS

WHEREAS, the Disclosing Party possesses certain confidential and proprietary information that it desires to disclose to the Receiving Party for the purpose of {purpose}; and

WHEREAS, the Receiving Party agrees to receive and maintain such information in confidence;

NOW, THEREFORE, in consideration of the mutual covenants and agreements contained herein, the parties agree as follows:

1. DEFINITION OF CONFIDENTIAL INFORMATION

"Confidential Information" means all non-public, proprietary, or confidential information disclosed by the Disclosing Party to the Receiving Party, whether orally, in writing, or in any other form, including but not limited to:

(a) Technical data, know-how, research, product plans, products, services, customers, customer lists, markets, software, developments, inventions, processes, formulas, technology, designs, drawings, engineering, hardware configuration information, marketing, finances, or other business information;

(b) Information that is marked, designated, or otherwise identified as "confidential" or "proprietary";

(c) Information that, by its nature or the circumstances of its disclosure, would reasonably be understood to be confidential or proprietary.

Confidential Information does not include information that:
(i) Is or becomes publicly available through no breach of this Agreement by the Receiving Party;
(ii) Was rightfully known by the Receiving Party prior to disclosure;
(iii) Is rightfully received from a third party without breach of any confidentiality obligation;
(iv) Is independently developed by the Receiving Party without use of or reference to the Confidential Information;
(v) Is required to be disclosed by law or court order, provided the Receiving Party gives the Disclosing Party prompt notice and cooperates in any effort to obtain protective treatment.

2. OBLIGATIONS OF RECEIVING PARTY

The Receiving Party agrees to:
(a) Hold and maintain the Confidential Information in strict confidence;
(b) Not disclose the Confidential Information to any third party without the prior written consent of the Disclosing Party;
(c) Use the Confidential Information solely for the purpose of {purpose};
(d) Take reasonable precautions to protect the confidentiality of the Confidential Information, using at least the same degree of care it uses to protect its own confidential information, but in no event less than reasonable care;
(e) Not make any copies of the Confidential Information except as necessary for the permitted use;
(f) Immediately notify the Disclosing Party upon discovery of any unauthorized use or disclosure of Confidential Information.

3. PERMITTED DISCLOSURES

The Receiving Party may disclose Confidential Information to its employees, officers, directors, advisors, and consultants who:
(a) Have a need to know such information for the permitted purpose;
(b) Are bound by confidentiality obligations at least as restrictive as those contained in this Agreement.

4. RETURN OF MATERIALS

Upon termination of this Agreement or upon written request by the Disclosing Party, the Receiving Party shall promptly return or destroy all documents, materials, and other tangible manifestations of Confidential Information and all copies thereof, and certify in writing that all such materials have been returned or destroyed. The Receiving Party may retain one copy for archival purposes, subject to the continuing obligations of confidentiality.

5. TERM

This Agreement shall remain in effect for a period of {term_years} years from the Effective Date, unless terminated earlier by mutual written agreement of the parties. The obligations of confidentiality shall survive termination of this Agreement and shall continue for a period of {term_years} years after termination, or such longer period as may be required by law.

6. NO LICENSE OR WARRANTY

Nothing in this Agreement grants the Receiving Party any right, title, or interest in or to any Confidential Information. All Confidential Information remains the property of the Disclosing Party. The Disclosing Party makes no representation or warranty as to the accuracy or completeness of any Confidential Information.

7. REMEDIES

The Receiving Party acknowledges that any breach of this Agreement may cause irrepaable harm to the Disclosing Party for which monetary damages would be inadequate. Accordingly, the Disclosing Party shall be entitled to seek injunctive relief and other equitable remedies, in addition to any other remedies available at law or in equity.

8. GOVERNING LAW AND JURISDICTION

This Agreement shall be governed by and construed in accordance with the laws of {jurisdiction}, without regard to its conflict of law principles. Any disputes arising under or in connection with this Agreement shall be subject to the exclusive jurisdiction of the courts located in {jurisdiction}.

9. GENERAL PROVISIONS

(a) This Agreement constitutes the entire agreement between the parties concerning the subject matter hereof and supersedes all prior agreements, understandings, negotiations, and discussions, whether oral or written.

(b) This Agreement may not be amended except in writing signed by both parties.

(c) If any provision of this Agreement is found to be unenforceable, the remainder of this Agreement shall remain in full force and effect.

(d) This Agreement may not be assigned by either party without the prior written consent of the other party.

(e) This Agreement may be executed in counterparts, each of which shall be deemed an original, but all of which together shall constitute one and the same instrument.

IN WITNESS WHEREOF, the parties have executed this Agreement as of the Effective Date.

DISCLOSING PARTY:                    RECEIVING PARTY:

_________________________            _________________________
{disclosing_party}                   {receiving_party}

By: _________________________        By: _________________________

Name: _______________________        Name: _______________________

Title: ______________________        Title: ______________________

Date: _______________________        Date: _______________________

"""

    elif "director" in document_type.lower() or "appointment" in document_type.lower():
        director_name = (
            merged_data.get('director_name') or 
            merged_data.get('name') or 
            '[DIRECTOR NAME]'
        )
        
        effective_date = (
            merged_data.get('effective_date') or 
            merged_data.get('date') or
            '[EFFECTIVE DATE]'
        )
        
        committees = merged_data.get('committees', [])
        
        document = f"""
RESOLUTION

WHEREAS, the Board of Directors wishes to appoint a new director;

NOW, THEREFORE, BE IT RESOLVED that {director_name} is hereby appointed as a director of the Company, effective {effective_date}.

"""
        if committees:
            document += "FURTHER RESOLVED that the director shall serve on the following committees:\n"
            for committee in committees:
                document += f"- {committee}\n"
            document += "\n"
        
        document += """
This resolution is effective immediately upon adoption by the Board of Directors.

"""
    
    elif "employment" in document_type.lower():
        employee_name = (
            merged_data.get('employee_name') or 
            merged_data.get('name') or 
            '[EMPLOYEE NAME]'
        )
        
        position = (
            merged_data.get('position') or 
            merged_data.get('title') or 
            merged_data.get('role') or
            '[POSITION]'
        )
        
        start_date = (
            merged_data.get('start_date') or 
            merged_data.get('effective_date') or 
            merged_data.get('date') or
            '[START DATE]'
        )
        
        salary = (
            merged_data.get('salary') or 
            merged_data.get('compensation') or 
            merged_data.get('pay') or
            '[SALARY]'
        )
        
        document = f"""
EMPLOYMENT AGREEMENT

This Employment Agreement is entered into between the Company and {employee_name} ("Employee").

1. POSITION
Employee shall serve as {position}, commencing on {start_date}.

2. COMPENSATION
Employee shall receive an annual salary of {salary}.

3. TERM
This Agreement shall continue until terminated by either party in accordance with the terms herein.

4. DUTIES
Employee agrees to perform all duties associated with the position and to devote full time and attention to the role.

5. CONFIDENTIALITY
Employee agrees to maintain the confidentiality of all proprietary information.

IN WITNESS WHEREOF, the parties have executed this Agreement.

"""
    
    else:
        # Generic document template
        document = """
TERMS AND CONDITIONS

1. GENERAL PROVISIONS
This document sets forth the terms and conditions governing the relationship between the parties.

2. OBLIGATIONS
Each party agrees to fulfill their respective obligations as set forth herein.

3. TERM AND TERMINATION
This agreement shall remain in effect until terminated in accordance with its terms.

4. GOVERNING LAW
This agreement shall be governed by applicable law.

IN WITNESS WHEREOF, the parties have executed this document.

"""
    
    # Store the document
    document_store[document_id] = document
    if session_id not in extracted_data_store:
        extracted_data_store[session_id] = {}
    extracted_data_store[session_id]['current_document_id'] = document_id
    
    return document


def apply_edits(edit_description: str, new_values: Dict[str, Any], document_id: Optional[str] = None) -> str:
    session_id = "default"
    
    print(f"DEBUG - apply_edits called with document_id: {document_id}")
    print(f"DEBUG - document_store keys: {list(document_store.keys())}")
    print(f"DEBUG - extracted_data_store: {extracted_data_store}")
    
    # Handle 'current' as a special keyword to get the current document
    if document_id == "current" or not document_id:
        if session_id in extracted_data_store and 'current_document_id' in extracted_data_store[session_id]:
            document_id = extracted_data_store[session_id]['current_document_id']
            print(f"DEBUG - Found document_id in session store: {document_id}")
        elif document_store:
            document_id = list(document_store.keys())[-1]
            print(f"DEBUG - Using last document from store: {document_id}")
        else:
            document_id = None
    
    if not document_id or document_id not in document_store:
        print(f"DEBUG - Document not found. document_id={document_id}, in store={document_id in document_store if document_id else False}")
        return "Error: No document found to edit. Please generate a document first."
    
    current_document = document_store[document_id]
    edited_document = current_document
    
    new_clause_text = new_values.pop('new_clause_text', None)

    if new_clause_text:
        general_provisions_match = re.search(r'(\d+)\.\s*GENERAL\s*PROVISIONS', edited_document, re.IGNORECASE | re.DOTALL)
        
        if general_provisions_match:
            current_last_section_number = int(general_provisions_match.group(1))
            new_clause_number = current_last_section_number
            next_section_number = current_last_section_number + 1
            
            new_clause_section = f"""

{new_clause_number}. **ADDITIONAL COVENANT**

{new_clause_text.strip()}

"""
            
            replacement_string = (
                new_clause_section + 
                f"\n\n{next_section_number}. GENERAL PROVISIONS"
            )
            
            pattern_to_replace = re.escape(general_provisions_match.group(0))
            
            edited_document = re.sub(
                pattern_to_replace, 
                replacement_string, 
                edited_document, 
                count=1, 
                flags=re.IGNORECASE | re.DOTALL
            )
        else:
            edited_document = edited_document.replace(
                "IN WITNESS WHEREOF", 
                f"\n\n**NEW CLAUSE**\n\n{new_clause_text.strip()}\n\nIN WITNESS WHEREOF"
            )

    
    text_to_find = new_values.pop('text_to_find', None)
    replacement_text = new_values.pop('replacement_text', None)

    if text_to_find and replacement_text:
        try:
            safe_text_to_find = re.escape(text_to_find)
            edited_document = re.sub(
                safe_text_to_find, 
                replacement_text, 
                edited_document, 
                count=1, 
                flags=re.IGNORECASE | re.DOTALL
            )
        except Exception:
            edited_document = edited_document.replace(text_to_find, replacement_text)
    
    
    for key, value in new_values.items():
        str_value = str(value)

        if key in ['effective_date', 'start_date', 'date', 'term', 'term_years']:
            pattern = r'(\d{4}-\d{2}-\d{2}|\[DATE\]|\[EFFECTIVE DATE\]|\[START DATE\]|\b\d+\s*year(?:s)?\b)'
            
            if key in ['term', 'term_years']:
                replacement_value = str_value
                term_match = re.search(r'period\s+of\s+(\d+)\s+years', edited_document, re.DOTALL)
                if term_match:
                    old_term_number = term_match.group(1)
                    edited_document = edited_document.replace(f"period of {old_term_number} years", f"period of {replacement_value} years", 1)
                    edited_document = edited_document.replace(f"continue for a period of {old_term_number} years", f"continue for a period of {replacement_value} years", 1)
                else:
                    edited_document = re.sub(pattern, str_value, edited_document, count=1, flags=re.IGNORECASE)
            else:
                edited_document = re.sub(pattern, str_value, edited_document, count=1, flags=re.IGNORECASE)

        elif key in ['name', 'director_name', 'employee_name', 'party_name', 'disclosing_party', 'receiving_party']:
            pattern = r'\[DIRECTOR NAME\]|\[EMPLOYEE NAME\]|\[PARTY NAME\]|\[NAME\]|\[DISCLOSING PARTY\]|\[RECEIVING PARTY\]'
            edited_document = re.sub(pattern, str_value, edited_document)
            
        else:
            edited_document = edited_document.replace(f'[{key.upper().replace(" ", "_")}]', str_value)
            fallback_key = f'**{key.title().replace("_", " ")} Missing**'
            edited_document = edited_document.replace(fallback_key, str_value)
    
    document_store[document_id] = edited_document
    
    return edited_document


def get_current_document(session_id: str = "default") -> Optional[str]:
    """Get the current document for a session."""
    if session_id in extracted_data_store and 'current_document_id' in extracted_data_store[session_id]:
        doc_id = extracted_data_store[session_id]['current_document_id']
        return document_store.get(doc_id)
    return None

