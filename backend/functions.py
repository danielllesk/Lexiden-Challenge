import json
from typing import Dict, Any, Optional

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
                "description": "Extract and store structured information from the conversation for document generation. Use this whenever the user provides relevant details like names, dates, terms, conditions, or any data needed for the document.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "extracted_data": {
                            "type": "object",
                            "description": "A structured object containing all relevant information extracted from the conversation. Include fields like names, dates, terms, conditions, parties involved, etc."
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
                "description": "Generate a complete legal document from the extracted information. Only call this when you have sufficient information to create a full document.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "document_type": {
                            "type": "string",
                            "description": "The type of legal document to generate"
                        },
                        "extracted_data": {
                            "type": "object",
                            "description": "All the structured data needed to generate the document"
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


def generate_document(document_type: str, extracted_data: Dict[str, Any]) -> str:
    """Generate a legal document from extracted data."""
    session_id = "default"
    document_id = f"{document_type}_{len(document_store)}"
    document = f"""
{document_type.upper()}

This {document_type} ("Agreement") is entered into on {extracted_data.get('effective_date', '[DATE]')} between the following parties:

"""
    if 'parties' in extracted_data:
        for i, party in enumerate(extracted_data['parties'], 1):
            document += f"Party {i}: {party}\n"
    elif 'party_name' in extracted_data:
        document += f"Party: {extracted_data['party_name']}\n"
    
    document += "\n"
    
    if document_type.lower() == "nda" or "non-disclosure" in document_type.lower():
        document += """
1. CONFIDENTIALITY OBLIGATIONS
The receiving party agrees to maintain the confidentiality of all proprietary information disclosed by the disclosing party.

2. TERM
This Agreement shall remain in effect for a period of {term} years from the effective date.

3. RETURN OF MATERIALS
Upon termination, all confidential materials shall be returned to the disclosing party.

4. GOVERNING LAW
This Agreement shall be governed by the laws of {jurisdiction}.

IN WITNESS WHEREOF, the parties have executed this Agreement as of the date first written above.

""".format(
            term=extracted_data.get('term', '2'),
            jurisdiction=extracted_data.get('jurisdiction', '[JURISDICTION]')
        )
    elif "director" in document_type.lower() or "appointment" in document_type.lower():
        director_name = extracted_data.get('director_name', extracted_data.get('name', '[DIRECTOR NAME]'))
        effective_date = extracted_data.get('effective_date', '[EFFECTIVE DATE]')
        committees = extracted_data.get('committees', [])
        
        document += f"""
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
        employee_name = extracted_data.get('employee_name', extracted_data.get('name', '[EMPLOYEE NAME]'))
        position = extracted_data.get('position', '[POSITION]')
        start_date = extracted_data.get('start_date', extracted_data.get('effective_date', '[START DATE]'))
        salary = extracted_data.get('salary', '[SALARY]')
        
        document += f"""
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
        # Generic and basic document template
        document += """
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
    """Apply edits to an existing document"""
    session_id = "default"
    
    if not document_id:
        if session_id in extracted_data_store and 'current_document_id' in extracted_data_store[session_id]:
            document_id = extracted_data_store[session_id]['current_document_id']
        else:
            # Use most recent document
            document_id = list(document_store.keys())[-1] if document_store else None
    
    if not document_id or document_id not in document_store:
        return "Error: No document found to edit. Please generate a document first."
    
    current_document = document_store[document_id]
    
    # This is just a simplified version, in production, you'd most likeltuse more sophisticated text replacement
    edited_document = current_document
    
    for key, value in new_values.items():
        if key in ['effective_date', 'start_date', 'date']:
            import re
            pattern = r'\d{4}-\d{2}-\d{2}|\[DATE\]|\[EFFECTIVE DATE\]|\[START DATE\]'
            edited_document = re.sub(pattern, str(value), edited_document, count=1)
        elif key in ['name', 'director_name', 'employee_name', 'party_name']:
            import re
            pattern = r'\[DIRECTOR NAME\]|\[EMPLOYEE NAME\]|\[PARTY NAME\]|\[NAME\]'
            edited_document = re.sub(pattern, str(value), edited_document)
        else:
            edited_document = edited_document.replace(f'[{key.upper()}]', str(value))
    
    document_store[document_id] = edited_document
    
    return edited_document


def get_current_document(session_id: str = "default") -> Optional[str]:
    """Get the current document for a session."""
    if session_id in extracted_data_store and 'current_document_id' in extracted_data_store[session_id]:
        doc_id = extracted_data_store[session_id]['current_document_id']
        return document_store.get(doc_id)
    return None

