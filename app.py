import streamlit as st
import ollama
import json
import time
import re

def get_available_models():
    try:
        models = ollama.list()
        return [model['name'] for model in models['models']]
    except Exception as e:
        st.error(f"Failed to fetch models: {str(e)}")
        return ["llama3.1"]  # Return default model if fetching fails

def make_api_call(messages, max_tokens, model_name, is_final_answer=False):
    for attempt in range(3):
        try:
            response = ollama.chat(
                model=model_name,
                messages=messages,
                options={
                    "num_predict": max_tokens,
                    "temperature": 0.2
                }
            )
            
            print(f"Raw API response: {response}")
            
            if 'message' not in response or 'content' not in response['message']:
                raise ValueError(f"Unexpected API response structure: {response}")
            
            content = response['message']['content']
            done_reason = response.get('done', False)
            
            # Remove any content before the first step or final answer
            content = re.sub(r'^.*?((?:### )?Step 1:|### Final Answer:)', r'\1', content, flags=re.DOTALL)
            
            # Parse the multi-step response
            steps = re.split(r'((?:### )?Step \d+:.*?(?=\n)|### Final Answer:.*?(?=\n))', content, flags=re.DOTALL)
            steps = [step.strip() for step in steps if step.strip()]

            parsed_steps = []
            for i in range(0, len(steps), 2):
                if i + 1 < len(steps):
                    title = steps[i].strip()
                    content = steps[i+1].strip()
                    
                    if "Final Answer" in title:
                        next_action = "final_answer"
                    else:
                        if not title.startswith("###"):
                            title = f"### {title}"
                        next_action = "continue"
                    
                    parsed_steps.append({
                        "title": title,
                        "content": content,
                        "next_action": next_action
                    })

            # If we found valid steps, return them along with done_reason
            if parsed_steps:
                return parsed_steps, done_reason
            
            # If no valid steps found, create a single step from the entire content
            return [{
                "title": "### Response",
                "content": content,
                "next_action": "final_answer"
            }], done_reason

        except Exception as e:
            if attempt == 2:
                if is_final_answer:
                    return [{"title": "### Error", "content": f"Failed to generate final answer after 3 attempts. Error: {str(e)}"}], None
                else:
                    return [{"title": "### Error", "content": f"Failed to generate step after 3 attempts. Error: {str(e)}", "next_action": "final_answer"}], None
            time.sleep(1)  # Wait for 1 second before retrying

    return None, None

def generate_response(prompt, model_name, max_tokens):
    messages = [
        {"role": "system", "content": """You are an expert AI assistant that explains your reasoning step by step. Follow these guidelines:

1. Structure your response with clear steps, each starting with "### Step X: [Step Title]" where X is the step number.
2. Use at least 3 steps in your reasoning BEFORE providing the final answer.
3. For each step, provide detailed content explaining your thought process.
4. Explore alternative answers and consider potential errors in your reasoning.
5. Use at least 3 different methods to derive the answer.
6. After your reasoning steps, end with a final step titled "### Final Answer:"
7. In the "### Final Answer:" step, provide a concise summary of your conclusion.

Example structure:
### Step 1: [Step Title]
[Step 1 content]

### Step 2: [Step Title]
[Step 2 content]

### Step 3: [Step Title]
[Step 3 content]

### Step 4: [Step Title]
[Step 4 content]

### Final Answer:
[Concise summary of the conclusion]

Remember to be aware of your limitations as an AI and use best practices in your reasoning. Aim for at least 4-5 steps before the final answer to ensure thorough analysis."""},
        {"role": "user", "content": prompt},
    ]
    
    reasoning_steps = []
    total_thinking_time = 0
    
    start_time = time.time()
    step_data_list, done_reason = make_api_call(messages, max_tokens, model_name)
    end_time = time.time()
    thinking_time = end_time - start_time
    total_thinking_time += thinking_time
    
    for step_data in step_data_list:
        reasoning_steps.append((step_data['title'].strip(), step_data['content'].strip(), thinking_time / len(step_data_list)))
        
        if step_data['next_action'] == 'final_answer':
            yield reasoning_steps, (step_data['title'], step_data['content'], thinking_time), total_thinking_time, done_reason
            return
    
    # This line should not be reached, but just in case:
    yield reasoning_steps, None, total_thinking_time, done_reason

def main():
    st.set_page_config(page_title="o1lama", page_icon="🦙", layout="wide")
    
    st.title("o1lama")
    
    st.markdown("Using Ollama to create reasoning chains that run locally and are similar in appearance to o1.")
    
    # Get available models and create a dropdown menu
    available_models = get_available_models()
    selected_model = st.selectbox("Select a model:", available_models)
    
    # Add dropdown for token selection with 1024 as default
    token_options = [512, 1024, 2048, 4096]
    selected_tokens = st.selectbox("Select max tokens:", token_options, index=token_options.index(1024))
    
    # Text area for user query (4 lines high)
    user_query = st.text_area("Enter your query:", placeholder="e.g., How many times does the letter 'R' appear in the word 'strawberry'?", height=120)
    
    # Create placeholder containers
    response_container = st.empty()
    time_container = st.empty()
    
    if user_query:
        # Clear previous response
        response_container.empty()
        time_container.empty()
        
        # Show "Generating response..." message with a spinner
        with st.spinner("Generating response..."):
            # Generate and display the response
            final_reasoning_steps = []
            final_answer = None
            final_done_reason = None
            for reasoning_steps, answer, total_thinking_time, done_reason in generate_response(user_query, selected_model, selected_tokens):
                final_reasoning_steps = reasoning_steps
                final_done_reason = done_reason
                if answer:
                    final_answer = answer

        with response_container.container():
            if len(final_reasoning_steps) > 1:  # Check if there are multiple steps
                st.markdown("### Reasoning")
                for step in final_reasoning_steps[:-1]:  # Exclude the last step
                    with st.expander(step[0], expanded=True):
                        st.markdown(step[1], unsafe_allow_html=True)
            
            if final_answer:
                st.markdown("### Final Answer")  # Display "Final Answer" without colon
                st.markdown(final_answer[1], unsafe_allow_html=True)
            elif final_reasoning_steps:  # If there's no final answer but there are steps
                st.markdown(final_reasoning_steps[-1][1], unsafe_allow_html=True)
            else:  # If there are no steps and no final answer
                st.markdown("No detailed reasoning steps were provided.")

        # Show total time
        if total_thinking_time is not None:
            time_container.markdown(f"**Total thinking time: {total_thinking_time:.2f} seconds**")
        
        # Display warning if response was truncated due to token limit
        if final_done_reason == "length":
            st.warning("The response was truncated due to token limit. Consider increasing the max token value for a more complete response.")


if __name__ == "__main__":
    main()

