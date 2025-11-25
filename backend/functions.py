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
    
    if document_type.lower() == "nda" or "non-disclosure" in document_type.lower():
        # Check for required fields
        required_fields = ['disclosing_party', 'receiving_party', 'effective_date', 'purpose', 'term', 'jurisdiction']
        missing = [f for f in required_fields if not extracted_data.get(f) and not extracted_data.get(f.replace('_party', '_name'))]
        
        if not extracted_data.get('disclosing_party'):
            extracted_data['disclosing_party'] = extracted_data.get('party_name', '[DISCLOSING PARTY]')
        if not extracted_data.get('receiving_party'):
            extracted_data['receiving_party'] = extracted_data.get('party_name', '[RECEIVING PARTY]')
        if not extracted_data.get('term'):
            extracted_data['term'] = extracted_data.get('term_years', '2')
    
    document = ""
    
    if document_type.lower() == "nda" or "non-disclosure" in document_type.lower():
        disclosing_party = extracted_data.get('disclosing_party', extracted_data.get('party_name', '[DISCLOSING PARTY]'))
        receiving_party = extracted_data.get('receiving_party', extracted_data.get('party_name', '[RECEIVING PARTY]'))
        effective_date = extracted_data.get('effective_date', '[EFFECTIVE DATE]')
        term_years = extracted_data.get('term', extracted_data.get('term_years', '2'))
        jurisdiction = extracted_data.get('jurisdiction', '[JURISDICTION/STATE]')
        purpose = extracted_data.get('purpose', '[PURPOSE OF DISCLOSURE]')
        
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

The Receiving Party acknowledges that any breach of this Agreement may cause irreparable harm to the Disclosing Party for which monetary damages would be inadequate. Accordingly, the Disclosing Party shall be entitled to seek injunctive relief and other equitable remedies, in addition to any other remedies available at law or in equity.

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

