FROM python:3.12-alpine                                                                                                                                                                                             
                                                                                                                                                                                                                    
# Install git (and tmux if you want the window title feature to work inside container)                                                                                                                              
RUN apk add --no-cache git tmux                                                                                                                                                                                     
                                                                                                                                                                                                                    
# Set working directory to the mounted workspace                                                                                                                                                                    
WORKDIR /workspace 
