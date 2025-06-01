import streamlit as st
import ollama
import json
import time
import re

def get_available_models():
    try:
        response = ollama.list()
        return [model.model for model in response.models]
    except Exception as e:
        st.error(f"Failed to fetch models: {str(e)}")
        return ["llama3.2"]  # Return default model if fetching fails

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
            
            
            if not hasattr(response, 'message') or not hasattr(response.message, 'content'):
                raise ValueError(f"Unexpected API response structure: {response}")
            
            content = response.message.content
            done_reason = response.done_reason if hasattr(response, 'done_reason') else 'completed'
            
            if not content:
                raise ValueError("Empty response content")
            
            
            # Remove any content before the first step or final answer
            content = re.sub(r'^.*?((?:### )?Step 1:|### Final Answer:)', r'\1', content, flags=re.DOTALL)
            
            
            # Parse the multi-step response - more robust pattern
            # Look for Step X: at the beginning of a line, capture everything until the next Step or Final Answer
            pattern = r'((?:### )?Step \d+:[^\n]*)'
            final_pattern = r'(### Final Answer:[^\n]*)'
            
            # Find all step headers and final answer
            step_headers = [(m.group(1), m.start(), m.end()) for m in re.finditer(pattern, content)]
            final_match = re.search(final_pattern, content)
            
            if final_match:
                step_headers.append((final_match.group(1), final_match.start(), final_match.end()))
            
            
            parsed_steps = []
            for i, (header, start, end) in enumerate(step_headers):
                # Get content until next header or end of string
                if i + 1 < len(step_headers):
                    content_end = step_headers[i + 1][1]
                else:
                    content_end = len(content)
                
                step_content = content[end:content_end].strip()
                
                if "Final Answer" in header:
                    next_action = "final_answer"
                else:
                    if not header.startswith("###"):
                        header = f"### {header}"
                    next_action = "continue"
                
                parsed_steps.append({
                    "title": header,
                    "content": step_content,
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

def create_step_statistics(reasoning_steps, total_thinking_time):
    """Create statistics about the reasoning process"""
    if not reasoning_steps:
        return None
    
    # Calculate statistics
    num_steps = len(reasoning_steps)
    avg_time_per_step = total_thinking_time / num_steps if num_steps > 0 else 0
    
    # Check for backtracking
    backtrack_count = 0
    for _, content, _ in reasoning_steps:
        if 'backtrack' in content.lower() or 'reconsider' in content.lower():
            backtrack_count += 1
    
    # Check for self-reflection steps
    reflection_count = sum(1 for title, _, _ in reasoning_steps if 'self-reflection' in title.lower() or 'reflection' in title.lower())
    
    # Calculate average content length
    avg_content_length = sum(len(content.split()) for _, content, _ in reasoning_steps) / num_steps if num_steps > 0 else 0
    
    return {
        'num_steps': num_steps,
        'total_time': total_thinking_time,
        'avg_time_per_step': avg_time_per_step,
        'backtrack_count': backtrack_count,
        'reflection_count': reflection_count,
        'avg_content_length': avg_content_length
    }


def generate_response(prompt, model_name, max_tokens):
    messages = [
        {"role": "system", "content": """You are an expert AI assistant that explains your reasoning step by step, incorporating dynamic Chain of Thought (CoT), reflection, and verbal reinforcement learning. Follow these guidelines:

1. Structure your response with clear steps, each starting with "### Step X: [Step Title]" where X is the step number.
2. Use at least 5 steps in your reasoning BEFORE providing the final answer.
3. For each step, provide detailed content explaining your thought process.
4. Explore multiple angles and approaches in your reasoning.
5. After each step, decide if you need another step or if you're ready to give the final answer.
6. Continuously adjust your reasoning based on intermediate results and reflections, adapting your strategy as you progress.
7. Regularly evaluate your progress, being critical and honest about your reasoning process.
8. Assign a quality score between 0.0 and 1.0 to guide your approach:
   - 0.8+: Continue current approach
   - 0.5-0.7: Consider minor adjustments
   - Below 0.5: Seriously consider backtracking and trying a different approach
   - If writing out the quality score do so in the format "**Quality Score:** 0.8" for example.
9. If unsure or if your score is low, backtrack and try a different approach, explaining your decision.
10. For mathematical problems, show all work explicitly. If using LaTeX, ensure it's within the step content, not in the step headers. Use $ for inline LaTeX and $$ for display LaTeX.
11. Explore multiple solutions individually if possible, comparing approaches in your reflections.
12. Write out all calculations and reasoning explicitly.
13. Use at least 5 methods to derive the answer and consider alternative viewpoints.
14. Be aware of your limitations as an AI and use best practices in your reasoning.
15. After every 3 steps, perform a detailed self-reflection on your reasoning so far, considering potential biases and alternative viewpoints.
16. End with a final step titled "### Final Answer:"
17. In the "### Final Answer:" step, provide a concise summary of your conclusion.

Example structure:
### Step 1: Understanding the Problem
Let me analyze what we're being asked to do here...
[Detailed thought process]
**Quality Score:** 0.9

### Step 2: Identifying Key Constraints
The main constraints are...
[Detailed analysis]
**Quality Score:** 0.8

### Step 3: Exploring Initial Approach
I'll start by considering...
[Step content]
**Quality Score:** 0.7

### Step 4: Self-Reflection
Looking at my progress so far...
[Detailed self-reflection on reasoning so far]
[Consider potential biases and alternative viewpoints]
[Decide whether to continue or change approach]
[Self-reflection content]

[Continue with more steps...]

### Final Answer:
[Concise summary of the conclusion]

Remember to be thorough in your analysis and adapt your approach based on your ongoing reflections."""},
        {"role": "user", "content": prompt},
    ]
    
    reasoning_steps = []
    total_thinking_time = 0
    
    start_time = time.time()
    step_data_list, done_reason = make_api_call(messages, max_tokens, model_name)
    end_time = time.time()
    thinking_time = end_time - start_time
    total_thinking_time += thinking_time
    
    for i, step_data in enumerate(step_data_list):
        reasoning_steps.append((step_data['title'].strip(), step_data['content'].strip(), thinking_time / len(step_data_list)))
        
        if step_data['next_action'] == 'final_answer':
            yield reasoning_steps, (step_data['title'], step_data['content'], thinking_time), total_thinking_time, done_reason
            return
    
    # This line should not be reached, but just in case:
    yield reasoning_steps, None, total_thinking_time, done_reason

def render_latex(content):
    # Replace "### Quality Score:" with "**Quality Score:**"
    content = content.replace("### Quality Score:", "**Quality Score:**")
    
    # Escape colons that are not part of LaTeX commands
    content = re.sub(r'(?<!\\\w):(?!\s*\\\w)', '\\:', content)
    
    # Split the content into LaTeX and non-LaTeX parts
    parts = re.split(r'(\\\[.*?\\\]|\$\$.*?\$\$|\$.*?\$)', content, flags=re.DOTALL)
    rendered_parts = []
    for part in parts:
        if part.startswith('\\[') and part.endswith('\\]'):
            # Render display LaTeX
            rendered_parts.append(st.latex(part.strip('\\[]')))
        elif part.startswith('$$') and part.endswith('$$'):
            # Render display LaTeX
            rendered_parts.append(st.latex(part.strip('$')))
        elif part.startswith('$') and part.endswith('$'):
            # Render inline LaTeX
            rendered_parts.append(st.latex(part.strip('$')))
        elif part.strip():
            # Render regular text
            rendered_parts.append(st.markdown(part))
    return rendered_parts


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
    graph_container = st.empty()
    
    if user_query:
        # Clear previous response
        response_container.empty()
        time_container.empty()
        graph_container.empty() 
        
        # Show "Generating response..." message with a spinner
        with st.spinner("Generating response..."):
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
                        render_latex(step[1])
            
            if final_answer:
                st.markdown("### Final Answer")  # Display "Final Answer" without colon
                render_latex(final_answer[1])
            elif final_reasoning_steps:  # If there's no final answer but there are steps
                render_latex(final_reasoning_steps[-1][1])
            else:  # If there are no steps and no final answer
                st.markdown("No detailed reasoning steps were provided.")


        # Display step statistics in its own container
        with graph_container.container():
            if final_reasoning_steps and len(final_reasoning_steps) > 1:
                # Exclude the final answer from statistics
                reasoning_steps_only = final_reasoning_steps[:-1] if final_answer else final_reasoning_steps
                stats = create_step_statistics(reasoning_steps_only, total_thinking_time)
                
                if stats:
                    st.subheader("📊 Reasoning Statistics")
                    
                    # Create columns for metrics
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.metric("Total Steps", stats['num_steps'])
                        st.metric("Avg Words/Step", f"{stats['avg_content_length']:.0f}")
                    
                    with col2:
                        st.metric("Total Time", f"{stats['total_time']:.1f}s")
                        st.metric("Avg Time/Step", f"{stats['avg_time_per_step']:.1f}s")
                    
                    with col3:
                        st.metric("Backtracking", stats['backtrack_count'])
                        st.metric("Self-Reflections", stats['reflection_count'])

        # Show total time
        if total_thinking_time is not None:
            time_container.markdown(f"**Total thinking time: {total_thinking_time:.2f} seconds**")
        
        # Display warning if response was truncated due to token limit
        if final_done_reason == "length":
            st.warning("The response was truncated due to token limit. Consider increasing the max token value for a more complete response.")


if __name__ == "__main__":
    main()

